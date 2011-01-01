import re
import copy
import sys

# Local imports
import utils

param_min_num_questions = 1

# Numbers of questions in which the number of tables is changed
param_table_limits = [8, 24, 55]
re_split_template = re.compile('{{([^{}]+)}}')

class ExamMaker(object):
    def __init__(self, num_questions, num_choices, template_filename,
                 output_file, variables, num_tables=0):
        self.num_questions = num_questions
        self.num_choices = num_choices
        self.num_tables = num_tables
        template = utils.read_file(template_filename)
        self.parts = re_split_template.split(template)
        self.output_file = output_file
        self.questions = None
        id_label, self.id_num_digits = id_num_digits(self.parts)
        self.__load_replacements(variables, id_label)

    def set_questions(self, questions):
        if len(questions) != self.num_questions:
            raise Exception('Incorrect number of questions')
        self.questions = questions

    def create_exam(self, model):
        if model is None or len(model) != 1 or ord(model) < 65 or \
                ord(model) > 90:
            raise Exception('Incorrect model value')
        answer_table = create_answer_table(self.num_questions, self.num_choices,
                                           model, self.num_tables)
        replacements = copy.copy(self.replacements)
        replacements['answer-table'] = answer_table
        replacements['model'] = model
        # Replacement keys are in odd positions of self.parts
        replaced = len(self.parts) * [None]
        replaced[::2] = self.parts[::2]
        replaced[1::2] = [self.__replace(key, replacements) \
                              for key in self.parts[1::2]]
        exam_text = ''.join(replaced)
        if self.output_file == sys.stdout:
            utils.write_to_stdout(exam_text)
        else:
            utils.write_file(self.output_file%model, exam_text)

    def __load_replacements(self, variables, id_label):
        self.replacements = copy.copy(variables)
        self.replacements['id-box'] = create_id_box(id_label,
                                                    self.id_num_digits)
        self.replacements['questions'] = ''

    def __replace(self, key, replacements):
        if key in replacements:
            return replacements[key]
        elif key.startswith('id-box'):
            return replacements['id-box']
        else:
            raise Exception('Unknown replacement key: ' + key)

def create_answer_table(num_questions, num_choices, model, num_tables = 0):
    """Returns a string with the answer tables of the asnwer sheet.

       Tables are LaTeX-formatted. 'num_questions' specifies the
       number of questions of the exam. 'num_choices' specifies the
       number of answers per question. 'num_tables' (optional)
       specifies the number of tables. If not specified or set to a
       non-positive vale, a number of tables that best fits the number
       of questions is chosen.

    """
    if num_questions < param_min_num_questions:
        raise Exception('Too few questions')
    if num_choices < 2:
        raise Exception('Too few answers per question')
    if num_tables <= 0:
        num_tables = __choose_num_tables(num_questions)
    elif num_tables * 2 > num_questions:
        raise Exception('Too many tables for the given number of questions')
    compact = (num_tables > 2)
    bits = utils.encode_model(model, num_tables, num_choices)
    bits_rows = __create_infobits(bits, num_tables, num_choices)
    tables, question_numbers = __table_geometry(num_questions, num_choices,
                                                num_tables)
    rows = __table_top(num_tables, num_choices, compact)
    for i, row_geometry in enumerate(tables):
        rows.append(__horizontal_line(row_geometry, num_choices, compact))
        rows.append(__build_row(i, row_geometry, question_numbers,
                                num_choices, bits_rows, compact))
    rows.append(r'\end{tabular}')
    rows.append(r'\end{center}')
    return '\n'.join(rows)


def create_id_box(label, num_digits):
    """Creates the ID box given a label to show and number of digits.

    """
    parts = [r'\begin{center}', r'\Large']
    parts.append(r'\begin{tabular}{l|' + num_digits * 'p{3mm}|' + '}')
    parts.append(r'\cline{2-%d}'%(1 + num_digits))
    parts.append(r'\textbf{%s}: '%label + num_digits * '& ' + r'\\')
    parts.append(r'\cline{2-%d}'%(1 + num_digits))
    parts.append(r'\end{tabular}')
    parts.append(r'\end{center}')
    return '\n'.join(parts)

def id_num_digits(parts):
    """Returns the tuple (label, number of digits) for the ID box.

       Receives the splitted text of the template for the exam, which
       may contain a key like 'id-box(9,NIA)' in an odd position, in
       which NIA is the label and 9 the number of digits. If the key
       does not exist in the template, returns (0, None).

    """
    # Replacement keys are in odd positions of the list
    for part in parts[1::2]:
        if part.startswith('id-box'):
            data = part[7:-1].split(',')
            # data[0] is num_digits; data[1] is label
            return data[1], int(data[0])
    return None, 0

def __choose_num_tables(num_questions):
    """Returns a good number of tables for the given number of questions."""
    num_tables = 1
    for numq in param_table_limits:
        if numq >= num_questions:
            break
        else:
            num_tables += 1
    return num_tables

def __table_geometry(num_questions, num_choices, num_tables):
    """Returns the geometry of the answer tables.

       The result is a tuple (tables, question_numbers) where:
       - 'tables' is a bidimensional list such that table[row][column]
       represents the number of answers for the question in 'row' /
       'column'. If 0, the question does not exist. If -1, a first row
       of infobits should be placed there; if -2, a second row.
       - 'question_numbers' is a list with the number of question of
       the first row of each table. The first question is numbered as
       1.

    """
    rows_per_table = num_questions // num_tables
    tables = rows_per_table * [num_tables * [num_choices]]
    question_numbers = []
    for i in range(0, num_tables):
        question_numbers.append(1 + i * rows_per_table)
    diff = num_questions - num_tables * rows_per_table
    if diff > 0:
        last_row = diff * [num_choices] + (num_tables - diff) * [-1]
        tables.append(last_row)
        acc = 0
        for i in range(1, num_tables):
            if i <= diff:
                acc += 1
            question_numbers[i] += acc
    if diff == 0:
        diff = num_tables
    tables.append(diff * [-1] + (num_tables - diff) * [-2])
    tables.append(diff * [-2] + (num_tables - diff) * [-0])
    return tables, question_numbers

def __horizontal_line(row_geometry, num_choices, compact):
    parts = []
    num_empty_columns = 1 if not compact else 0
    first = 2
    for i, geometry in enumerate(row_geometry):
        if geometry > 0 or geometry == -1:
            parts.append(r'\cline{%d-%d}'%(first, first + num_choices - 1))
        first += 1 + num_empty_columns + num_choices
    return ' '.join(parts)

def __table_top(num_tables, num_choices, compact):
    middle_sep_format = 'p{3mm}' if not compact else ''
    middle_sep_header = ' & & ' if not compact else ' & '
    l = middle_sep_format.join(num_tables
                               * ['|'.join(['r'] + num_choices * ['c'] + [''])])
    l = r'\begin{tabular}{' + l + '}'
    lines = [r'\begin{center}', r'\large', l]
    parts = []
    for i in range(0, num_tables):
        parts_internal = []
        parts_internal.append(r'\multicolumn{1}{c}{}')
        for j in range(0, num_choices):
            parts_internal.append(r'\multicolumn{1}{c}{%s}'%chr(65 + j))
        parts.append(' & '.join(parts_internal))
    lines.append(middle_sep_header.join(parts) + r' \\')
    return lines

def __build_row(num_row, row_geometry, question_numbers, num_choices,
                infobits_row, compact):
    parts = []
    num_empty_columns = 1 if not compact else 0
    skip_cells = 0
    for i, geometry in enumerate(row_geometry):
        if geometry > 0:
            parts.append(__build_question_cell(num_row + question_numbers[i],
                                               geometry))
        elif geometry == -1:
            parts.append(infobits_row[0][i])
        elif geometry == -2:
            parts.append(infobits_row[1][i])
        else:
            skip_cells += 1 + num_empty_columns + num_choices
    row = ' & & '.join(parts) if not compact else ' & '.join(parts)
    if skip_cells > 0:
        row += r' & \multicolumn{%d}{c}{}'%skip_cells
    return row + r' \\'

def __build_question_cell(num_question, num_choices):
    parts = [str(num_question)]
    for i in range(0, num_choices):
        parts.append(r'\light{%s}'%chr(65 + i))
    return ' & '.join(parts)

def __create_infobits(bits, num_tables, num_choices):
    column_active = r'\multicolumn{1}{c}{$\blacksquare$}'
    column_inactive = r'\multicolumn{1}{c}{}'
    parts = [[], []]
    for i in range(0, num_tables):
        data = bits[i * num_choices: (i + 1) * num_choices]
        for j in (0, 1):
            val = (j == 1)
            components = [column_inactive]
            for bit in data:
                if val ^ bit:
                    components.append(column_active)
                else:
                    components.append(column_inactive)
            parts[j].append(' & '.join(components))
    return parts

def re_id_box_replacer(match):
    """Takes a re.match object and returns the id box.

    Two groups expected: (1) number of digits; (2) label to show.

    """
    return create_id_box(match.group(2), int(match.group(1)))
