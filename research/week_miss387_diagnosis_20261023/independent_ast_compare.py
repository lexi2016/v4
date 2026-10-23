#!/usr/bin/env python3
"""Read-only independent shunting-yard check of frozen V192 text vs saved AST renderings.
Does not import or call the original formula parser, numerical helpers, or market evaluators.
"""
from decimal import Decimal
import hashlib
import json
import re
from pathlib import Path

SOURCE = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_v192_signal_pool_return_stability_v1/intake/unpacked/base_bundle/formula/V192ORIG_UTF8.txt')
DETAILS = Path('/Users/lexi/Desktop/学习/因子工厂/research/week_miss387_diagnosis_20261023/DETAILS.jsonl')
TOKEN = re.compile(r"\s+|(?:\d+(?:\.\d*)?|\.\d+)|'[^']*'|[A-Za-z_][A-Za-z_0-9]*|<=|>=|<>|!=|[()+*/<>=,-]")
PRECEDENCE = {'OR': 1, 'AND': 2, '=': 3, '<': 3, '>': 3, '<=': 3, '>=': 3, '<>': 3, '!=': 3, '+': 4, '-': 4, '*': 5, '/': 5, 'u+': 6, 'u-': 6}
BINARY = set(PRECEDENCE) - {'u+', 'u-'}


def lex(expression):
    out, pos = [], 0
    while pos < len(expression):
        match = TOKEN.match(expression, pos)
        if not match:
            raise ValueError(('unlexed', pos, expression[pos:pos + 20]))
        token = match.group()
        pos = match.end()
        if not token.isspace():
            out.append(token.upper() if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', token) else token)
    return out


def parse(expression):
    """Convert infix text to RPN with shunting-yard, then build a canonical tree."""
    tokens = lex(expression)
    output, operators, frames = [], [], []
    expect_operand = True
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", token):
            output.append(('number', str(Decimal(token).normalize())))
            expect_operand = False
        elif token.startswith("'") and token.endswith("'"):
            output.append(('string', token[1:-1]))
            expect_operand = False
        elif token in BINARY:
            if token in ('+', '-') and expect_operand:
                operators.append('u' + token)
            else:
                while (operators and isinstance(operators[-1], str)
                       and operators[-1] in PRECEDENCE
                       and (PRECEDENCE[operators[-1]] > PRECEDENCE[token]
                            or (PRECEDENCE[operators[-1]] == PRECEDENCE[token]
                                and token not in ('u+', 'u-')))):
                    output.append(('operator', operators.pop()))
                operators.append(token)
                expect_operand = True
        elif re.fullmatch(r'[A-Z_][A-Z_0-9]*', token):
            if i + 1 < len(tokens) and tokens[i + 1] == '(':
                operators.append(('function', token))
            else:
                output.append(('name', token))
                expect_operand = False
        elif token == '(':
            is_function = bool(operators and isinstance(operators[-1], tuple) and operators[-1][0] == 'function')
            operators.append('(')
            frames.append([is_function, 0])
            expect_operand = True
        elif token == ',':
            while operators and operators[-1] != '(':
                output.append(('operator', operators.pop()))
            if not frames or not frames[-1][0]:
                raise ValueError(('comma_outside_function', i))
            frames[-1][1] += 1
            expect_operand = True
        elif token == ')':
            while operators and operators[-1] != '(':
                output.append(('operator', operators.pop()))
            if not operators or not frames:
                raise ValueError(('unmatched_parenthesis', i))
            operators.pop()
            is_function, commas = frames.pop()
            if is_function:
                if not operators or not (isinstance(operators[-1], tuple) and operators[-1][0] == 'function'):
                    raise ValueError(('missing_function', i))
                output.append(('call', operators.pop()[1], commas + 1))
            expect_operand = False
        else:
            raise ValueError(('unsupported_token', token, i))
        i += 1
    while operators:
        if operators[-1] == '(' or (isinstance(operators[-1], tuple) and operators[-1][0] == 'function'):
            raise ValueError('unclosed_parenthesis_or_call')
        output.append(('operator', operators.pop()))
    if frames:
        raise ValueError('unclosed_frame')
    stack = []
    for item in output:
        if item[0] == 'operator':
            op = item[1]
            if op.startswith('u'):
                stack.append(('unary', op[1], (stack.pop(),)))
            else:
                right, left = stack.pop(), stack.pop()
                stack.append(('binary', op, (left, right)))
        elif item[0] == 'call':
            _, name, arity = item
            if len(stack) < arity:
                raise ValueError(('call_stack_underflow', name, arity, len(stack)))
            args = tuple(stack[-arity:])
            del stack[-arity:]
            stack.append(('call', name, args))
        else:
            stack.append(item)
    if len(stack) != 1:
        raise ValueError(('final_stack_size', len(stack)))
    return stack[0]


def names(tree):
    if tree[0] == 'name':
        return {tree[1]}
    if tree[0] in ('number', 'string'):
        return set()
    found = set()
    for child in tree[2]:
        found.update(names(child))
    return found


def main():
    source_bytes = SOURCE.read_bytes()
    source_text = source_bytes.decode('utf-8-sig')
    assignments = []
    for line_number, line in enumerate(source_text.splitlines(), 1):
        statement = line.strip().rstrip(';').strip()
        match = re.match(r'^([A-Z][A-Z0-9_]*)\s*(?::=|:)\s*(.*)$', statement, re.I)
        if not match:
            raise ValueError(('not_assignment', line_number))
        assignments.append((match.group(1).upper(), match.group(2), line_number))

    # Read only the first event's source-expression/dependency projection from DETAILS.
    with DETAILS.open(encoding='utf-8') as stream:
        saved = json.loads(next(stream))['signal']['a_assignments']

    mismatches, parsed = [], {}
    source_names = [name for name, _, _ in assignments]
    saved_names = list(saved)
    if source_names != saved_names:
        mismatches.append({'kind': 'assignment_name_or_order'})
    if len(set(source_names)) != len(source_names):
        mismatches.append({'kind': 'duplicate_source_assignment_name'})
    for name, expression, line_number in assignments:
        try:
            source_tree = parse(expression)
            parsed[name] = source_tree
        except Exception as exc:
            mismatches.append({'kind': 'source_parse_error', 'name': name, 'line': line_number, 'error': repr(exc)})
            continue
        try:
            saved_tree = parse(saved[name]['expression'])
        except Exception as exc:
            mismatches.append({'kind': 'saved_expression_parse_error', 'name': name, 'error': repr(exc)})
            continue
        if source_tree != saved_tree:
            mismatches.append({'kind': 'tree_mismatch', 'name': name})
        if names(source_tree) != set(saved[name]['dependencies']):
            mismatches.append({'kind': 'dependency_mismatch', 'name': name})

    # Verify no assignment references a later assignment, and check the explicit XG OR/AND priority.
    assignment_set, seen, forward = set(source_names), set(), []
    for name, _, line_number in assignments:
        if name not in parsed:
            continue
        unresolved = sorted(ref for ref in names(parsed[name]) if ref in assignment_set and ref not in seen)
        if unresolved:
            forward.append({'name': name, 'line': line_number, 'references': unresolved})
        seen.add(name)
    xg_priority = parse('ENTRYPOOL AND (B2ROLE OR (B3ROLE AND RISK0<45))')
    xg_matches_priority = parsed.get('XG') == xg_priority
    if not xg_matches_priority:
        mismatches.append({'kind': 'xg_priority_structure_mismatch'})

    print(json.dumps({
        'result': 'PASS' if not mismatches and len(assignments) == len(saved) == 255 and not forward else 'FAIL',
        'method': 'independent_shunting_yard_source_and_saved_expression_parse',
        'original_parser_imported_or_called': False,
        'formula_source': str(SOURCE),
        'formula_source_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'saved_ast_source': str(DETAILS),
        'saved_ast_source_sha256': hashlib.sha256(DETAILS.read_bytes()).hexdigest(),
        'saved_ast_scope': 'first JSONL event signal.a_assignments only',
        'source_assignment_count': len(assignments),
        'saved_assignment_count': len(saved),
        'unique_source_assignment_names': len(set(source_names)),
        'assignment_name_order_match': source_names == saved_names,
        'tree_and_dependency_mismatch_count': len(mismatches),
        'forward_assignment_reference_count': len(forward),
        'xg_priority_structure_match': xg_matches_priority,
        'mismatches': mismatches,
        'forward_references': forward,
        'scope_limit': 'Checks source text against saved AST expression rendering; does not independently evaluate numeric formula values or certify native TDX/Futu semantics.'
    }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
