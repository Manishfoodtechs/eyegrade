# Eyegrade: grading multiple choice questions with a webcam
# Copyright (C) 2013 Jesus Arias Fisteus
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see
# <http://www.gnu.org/licenses/>.
#
import sqlite3
import os
import os.path
import csv

import utils


class SessionDB(object):
    """Access to a session SQLite database.

    This class encapsulates access functions to the session database.

    """

    _table_session = """
        CREATE TABLE Session (
            dimensions TEXT NOT NULL,
            correct_weight TEXT,
            incorrect_weight TEXT,
            blank_weight TEXT,
            id_num_digits INTEGER NOT NULL,
            survey_mode INTEGER NOT NULL,
            left_to_right_numbering INTEGER NOT NULL,
            capture_pattern TEXT NOT NULL
        )"""

    _table_solutions = """
        CREATE TABLE Solutions (
            model TEXT NOT NULL,
            solutions TEXT NOT NULL
        )"""

    _table_permutations = """
        CREATE TABLE Permutations (
            model TEXT NOT NULL,
            permutations TEXT NOT NULL
        )"""

    _table_exams = """
        CREATE TABLE Exams (
            exam_id INTEGER PRIMARY KEY NOT NULL,
            student INTEGER,
            model TEXT,
            correct INTEGER,
            incorrect INTEGER,
            blank INTEGER,
            score REAL,
            FOREIGN KEY(student) REFERENCES Students(db_id)
        )"""

    _table_students = """
        CREATE TABLE Students (
            db_id INTEGER PRIMARY KEY NOT NULL,
            student_id TEXT,
            name TEXT,
            email TEXT,
            group_id INTEGER NOT NULL,
            sequence_num INTEGER NOT NULL,
            FOREIGN KEY(group_id) REFERENCES StudentGroups(group_id)
        )"""

    _table_student_groups = """
        CREATE TABLE StudentGroups (
            group_id INTEGER PRIMARY KEY NOT NULL,
            group_name TEXT NOT NULL
        )"""

    _table_answers = """
        CREATE TABLE Answers (
            exam_id INTEGER NOT NULL,
            question INTEGER NOT NULL,
            answer INTEGER NOT NULL,
            FOREIGN KEY(exam_id) REFERENCES Exams(exam_id)
        )"""

    _table_answer_cells = """
        CREATE TABLE AnswerCells (
            exam_id INTEGER NOT NULL,
            question INTEGER NOT NULL,
            choice INTEGER NOT NULL,
            center_x INTEGER NOT NULL,
            center_y INTEGER NOT NULL,
            diagonal INTEGER NOT NULL,
            lux INTEGER,
            luy INTEGER,
            rux INTEGER,
            ruy INTEGER,
            ldx INTEGER,
            ldy INTEGER,
            rdx INTEGER,
            rdy INTEGER,
            FOREIGN KEY(exam_id) REFERENCES Exams(exam_id)
        )"""

    _table_id_cells = """
        CREATE TABLE IdCells (
            exam_id INTEGER NOT NULL,
            digit INTEGER NOT NULL,
            lux INTEGER NOT NULL,
            luy INTEGER NOT NULL,
            rux INTEGER NOT NULL,
            ruy INTEGER NOT NULL,
            ldx INTEGER NOT NULL,
            ldy INTEGER NOT NULL,
            rdx INTEGER NOT NULL,
            rdy INTEGER NOT NULL,
            FOREIGN KEY(exam_id) REFERENCES Exams(exam_id)
        )"""

    def __init__(self, session_file):
        """Opens a session database.

        For opening an existing session, just pass as `session_file` the
        session DB file name or the sesion's directory name.

        """
        if os.path.isdir(session_file):
            db_file = os.path.join(session_file, 'session.eyedb')
            self.session_dir = session_file
        else:
            db_file = session_file
            self.session_dir = os.path.dirname(db_file)
        self._check_session_directory()
        self.conn = sqlite3.connect(db_file)
        self.conn.row_factory = sqlite3.Row
        self._enable_foreign_key_constrains()
        self.exam_config = self._load_exam_config()
        self.students = self.load_students()
        self._compute_num_questions_and_choices()
        self.capture_save_func = None

    def close(self):
        self.conn.close()

    def list_exams(self):
        exams = []
        cursor = self.conn.cursor()
        for row in cursor.execute('SELECT * FROM Exams'):
            exams.append(SessionDB._create_exam_from_db(row))
        return exams

    def store_exam(self, exam_id, capture, decisions, score):
        if decisions.student is not None:
            if not decisions.student.is_in_database:
                self.store_new_student(decisions.student, commit=False)
            student_db_id = decisions.student.db_id
        else:
            student_db_id = None
        cursor = self.conn.cursor()
        cursor.execute('INSERT INTO Exams VALUES '
                       '(?, ?, ?, ?, ?, ?, ?)',
                       (exam_id, student_db_id, decisions.model,
                        score.correct, score.incorrect, score.blank,
                        score.score))
        self._store_answers(exam_id, decisions.answers, commit=False)
        self._store_answer_cells(exam_id, capture.answer_cells, commit=False)
        self._store_id_cells(exam_id, capture.id_cells, commit=False)
        self.conn.commit()
        self._save_captures(exam_id, capture, decisions)

    def store_new_student(self, student, commit=True):
        cursor = self.conn.cursor()
        if student.group_id is None:
            student.group_id = 0
        if student.sequence_num is None:
            student.sequence_num = self._group_max_seq(student.group_id) + 1
        cursor.execute('INSERT INTO Students '
                       '(student_id, name, email, group_id, sequence_num) '
                       'VALUES (:student_id, :name, :email, :group_id, '
                       '        :sequence_num)',
                       student.__dict__)
        student.db_id = cursor.lastrowid
        if commit:
            self.conn.commit()

    def load_students(self):
        self.students = {}
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM Students')
        for row in cursor:
            student = utils.Student(row['db_id'], row['student_id'],
                                    row['name'], row['email'],
                                    row['group_id'], row['sequence_num'],
                                    is_in_database=True)
            self.students[student.student_id] = student
        return self.students

    def next_exam_id(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT MAX(exam_id) FROM Exams')
        result = cursor.fetchone()[0]
        if result is not None:
            return int(result) + 1
        else:
            return 1

    def save_legacy_answers(self, csv_dialect):
        answers_file = os.path.join(self.session_dir, 'eyegrade-answers.csv')
        with open(answers_file, "wb") as f:
            writer = csv.writer(f, dialect = csv_dialect)
            for exam in self.exams_iterator():
                data = [
                    exam['exam_id'],
                    exam['student_id'] if exam['student_id'] else -1,
                    exam['model'] if exam['model'] else '?',
                    exam['correct'],
                    exam['incorrect'],
                    exam['score'] if exam['score'] is not None else '?',
                    '/'.join([str(answer) for answer in exam['answers']]),
                    ]
                writer.writerow(data)

    def exams_iterator(self):
        cursor = self.conn.cursor()
        for row in cursor.execute('SELECT '
                                  'exam_id, student_id, model, '
                                  'correct, incorrect, score '
                                  'FROM Exams '
                                  'LEFT JOIN Students ON student = db_id'):
            exam = dict(row)
            exam['answers'] = self.read_answers(exam['exam_id'])
            yield exam

    def read_answers(self, exam_id):
        answers = [0] * self.exam_config.num_questions
        cursor = self.conn.cursor()
        for row in cursor.execute('SELECT question, answer FROM Answers '
                                  'WHERE exam_id = ?',
                                  (exam_id, )):
            answers[row['question']] = row['answer']
        return answers

    def _check_session_directory(self):
        db_file = os.path.join(self.session_dir, 'session.eyedb')
        if not os.path.exists(db_file):
            raise utils.EyegradeException('', key='no_session_db')
        if not check_file_is_sqlite(db_file):
            raise utils.EyegradeException('', key='no_session_db')
        if (not os.path.exists(os.path.join(self.session_dir, 'captures'))
            or not os.path.exists(os.path.join(self.session_dir, 'internal'))):
            raise utils.EyegradeException('', key='corrupt_session_dir')

    def _save_captures(self, exam_id, capture, decisions):
        name = utils.capture_name(self.exam_config.capture_pattern,
                                  exam_id, decisions.student)
        drawn_name = os.path.join(self.session_dir, 'captures', name)
        raw_name = os.path.join(self.session_dir, 'internal',
                                'raw-{0}.png'.format(exam_id))
        if self.capture_save_func:
            self.capture_save_func(drawn_name)
        else:
            capture.save_image_drawn(drawn_name)
        capture.save_image_raw(raw_name)

    def _get_cell_geometries(self, exam_id, load_corners=False):
        if not load_corners:
            query = ('SELECT question, choice, center_x, center_y, diagonal '
                     'FROM CellGeometries WHERE exam_id = ?')
        else:
            query = 'SELECT * FROM CellGeometries WHERE exam_id = ?'
        cursor = self.conn.cursor()
        return [row for row in cursor.execute(query, exam_id)]

    def _compute_num_questions_and_choices(self):
        self.num_choices = []
        self.num_questions = 0
        dimensions = self.exam_config.dimensions
        for table in dimensions:
            self.num_choices.extend([table[0]] * table[1])
            self.num_questions += table[1]

    def _load_exam_config(self):
        self.exam_config = utils.ExamConfig()
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM Session')
        row = cursor.fetchone()
        if row is None:
            raise utils.EyegradeException('', key='session_invalid')
        self.exam_config.set_dimensions(row['dimensions'])
        self.exam_config.id_num_digits = row['id_num_digits']
        self.exam_config.survey_mode = \
            True if row['survey_mode'] else False
        self.exam_config.left_to_right_numbering = \
            True if row['left_to_right_numbering'] else False
        if row['correct_weight'] is not None:
            self.exam_config.set_score_weights(row['correct_weight'],
                                               row['incorrect_weight'],
                                               row['blank_weight'])
        else:
            self.exam_config.score_weights = None
        self.exam_config.capture_pattern = row['capture_pattern']
        for row in cursor.execute('SELECT * FROM Solutions'):
            self.exam_config.set_solutions(row['model'], row['solutions'])
        for row in cursor.execute('SELECT * FROM Permutations'):
            self.exam_config.set_permutations(row['model'],
                                              row['permutations'])
        return self.exam_config

    def _change_answer(self, exam_id, question, new_answer):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE Answers SET answer = ?'
                       'WHERE exam_id = ? AND question = ?',
                       (new_answer, exam_id, question))
        self.conn.commit()

    def _change_score(self, exam_id, correct, incorrect, blank, score):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE Exams SET correct = ?, incorrect = ?,'
                       '                 blank = ?, score = ?'
                       'WHERE exam_id = ?',
                       (correct, incorrect, blank, score, exam_id))
        self.conn.commit()

    def _group_max_seq(self, group_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT MAX(sequence_num) FROM Students '
                       'WHERE group_id = ?',
                       (group_id, ))
        result = cursor.fetchone()[0]
        if result is not None:
            return int(result)
        else:
            return -1

    def _store_answers(self, exam_id, answers, commit=True):
        data = []
        for i, answer in enumerate(answers):
            data.append((exam_id, i, answer))
        if len(data) > 0:
            cursor = self.conn.cursor()
            cursor.executemany('INSERT INTO Answers VALUES (?, ?, ?)', data)
            if commit:
                self.conn.commit()

    def _store_answer_cells(self, exam_id, answer_cells, commit=True):
        data = []
        for i, question_cells in enumerate(answer_cells):
            for j, cell in enumerate(question_cells):
                item = (exam_id, i, j, cell.center[0], cell.center[1],
                        cell.diagonal,
                        cell.plu[0], cell.plu[1], cell.pru[0], cell.pru[1],
                        cell.pld[0], cell.pld[1], cell.prd[0], cell.prd[1])
                data.append(item)
        if len(data) > 0:
            cursor = self.conn.cursor()
            cursor.executemany('INSERT INTO AnswerCells VALUES '
                               '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                               data)
            if commit:
                self.conn.commit()

    def _store_id_cells(self, exam_id, id_cells, commit=True):
        data = []
        for i, cell in enumerate(id_cells):
            item = (exam_id, i,
                    cell.plu[0], cell.plu[1], cell.pru[0], cell.pru[1],
                    cell.pld[0], cell.pld[1], cell.prd[0], cell.prd[1])
            data.append(item)
        if len(data) > 0:
            cursor = self.conn.cursor()
            cursor.executemany('INSERT INTO IdCells VALUES '
                               '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                               data)
            if commit:
                self.conn.commit()

    def _enable_foreign_key_constrains(self):
        cursor = self.conn.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')


def check_file_is_sqlite(filename):
    try:
        with open(filename, 'r') as f:
            data = f.read(16)
        if data == 'SQLite format 3\x00':
            is_sqlite = True
        else:
            is_sqlite = False
    except:
        is_sqlite = False
    return is_sqlite

def create_session_directory(dir_name, exam_data, id_files):
    """Create the session database and directory layout.

    `dir_name` must be an empty directory that already exists. If
    it does not exist, it is created here.

    """
    if not os.path.isdir(dir_name):
        os.mkdir(dir_name)
    os.mkdir(os.path.join(dir_name, 'captures'))
    os.mkdir(os.path.join(dir_name, 'internal'))
    db_file = os.path.join(dir_name, 'session.eyedb')
    _create_session_db(db_file, exam_data, id_files)

def _create_session_db(db_file, exam_data, id_files):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    _save_exam_config(conn, exam_data)
    for id_file in id_files:
        _save_student_list(conn, id_file)
    conn.commit()

def _create_tables(conn):
    cursor = conn.cursor()
    cursor.execute(SessionDB._table_session)
    cursor.execute(SessionDB._table_solutions)
    cursor.execute(SessionDB._table_permutations)
    cursor.execute(SessionDB._table_exams)
    cursor.execute(SessionDB._table_students)
    cursor.execute(SessionDB._table_student_groups)
    cursor.execute(SessionDB._table_answers)
    cursor.execute(SessionDB._table_answer_cells)
    cursor.execute(SessionDB._table_id_cells)
    cursor.execute('INSERT INTO StudentGroups VALUES (0, "INSERTED")')

def _save_exam_config(conn, exam_data):
    if exam_data.score_weights is None:
        weights = (None, None, None)
    else:
        weights = exam_data.score_weights
    cursor = conn.cursor()
    cursor.execute('INSERT INTO Session VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (exam_data.format_dimensions(),
         exam_data.format_weight(weights[0]),
         exam_data.format_weight(weights[1]),
         exam_data.format_weight(weights[2]),
         exam_data.id_num_digits,
         1 if exam_data.survey_mode else 0,
         1 if exam_data.left_to_right_numbering else 0,
         exam_data.capture_pattern))
    for model in exam_data.solutions:
        cursor.execute('INSERT INTO Solutions VALUES (?, ?)',
                       (model, exam_data.format_solutions(model)))
    for model in exam_data.permutations:
        cursor.execute('INSERT INTO Permutations VALUES (?, ?)',
                      (model, exam_data.format_permutations(model)))

def _save_student_list(conn, students_file):
    students = utils.read_student_ids_same_order(filename=students_file,
                                                 with_names=True)
    _create_student_group(conn, os.path.basename(students_file), students)

def _create_student_group(conn, group_name, student_list):
    """Creates a new student group and loads students in it.

    The student list is a list of tuples (student_id, name, email).

    """
    cursor = conn.cursor()
    cursor.execute('INSERT INTO StudentGroups (group_name) VALUES (?)',
                   (group_name,))
    group_id = cursor.lastrowid
    if len(student_list) > 0:
        internal_list = []
        for i, data in enumerate(student_list):
            internal_list.append((data[0], data[1], data[2], group_id, i))
        cursor.executemany('INSERT INTO Students '
                           '(student_id, name, email, group_id,'
                           ' sequence_num) VALUES '
                            '(?, ?, ?, ?, ?)',
                           internal_list)
