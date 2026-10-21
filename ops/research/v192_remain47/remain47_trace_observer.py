"""Static-prepared value observer. Importing this file does not load data or score.

The controller must approve a frozen execution contract before using instrument().
Every wrapper returns the exact incoming object; it never re-evaluates an expression.
"""
from __future__ import annotations
import ast
import copy
import hashlib
import json

VALUE_NAME = "__v192_observed_value__"
ASSIGN_NAME = "__v192_observed_assignment__"


def ast_sha(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


class ValueObserverTransform(ast.NodeTransformer):
    def __init__(self, function_name):
        self.function_name = function_name
        self.entries = []

    def wrap(self, node):
        unwrapped = RemoveObserver().visit(copy.deepcopy(node))
        identity = len(self.entries)
        self.entries.append(dict(id=identity, function=self.function_name,
            kind=type(node).__name__, line=node.lineno,
            column=node.col_offset, expression=ast.unparse(unwrapped),
            original_ast_sha256=ast_sha(unwrapped)))
        # The original expression is evaluated once as the middle argument.
        wrapped = ast.Call(func=ast.Name(id=VALUE_NAME, ctx=ast.Load()),
            args=[ast.Constant(identity), node,
                  ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[])],
            keywords=[])
        return ast.copy_location(wrapped, node)

    def visit_BinOp(self, node):
        return self.wrap(self.generic_visit(node))

    def visit_BoolOp(self, node):
        return self.wrap(self.generic_visit(node))

    def visit_Compare(self, node):
        return self.wrap(self.generic_visit(node))

    def visit_UnaryOp(self, node):
        return self.wrap(self.generic_visit(node))

    def visit_IfExp(self, node):
        return self.wrap(self.generic_visit(node))

    def visit_Call(self, node):
        return self.wrap(self.generic_visit(node))

    def assignment(self, node, targets):
        original_targets = [ast.unparse(x) for x in targets]
        node = self.generic_visit(node)
        marker = dict(function=self.function_name, line=node.lineno,
                      kind=type(node).__name__, targets=original_targets)
        sentinel = ast.Expr(value=ast.Call(
            func=ast.Name(id=ASSIGN_NAME, ctx=ast.Load()),
            args=[ast.Constant(json.dumps(marker, sort_keys=True)),
                  ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[])],
            keywords=[]))
        return [node, ast.copy_location(sentinel, node)]

    def visit_Assign(self, node):
        return self.assignment(node, node.targets)

    def visit_AnnAssign(self, node):
        return self.assignment(node, [node.target])

    def visit_AugAssign(self, node):
        return self.assignment(node, [node.target])


class RemoveObserver(ast.NodeTransformer):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == VALUE_NAME:
            assert len(node.args) == 3 and not node.keywords
            return self.visit(node.args[1])
        return self.generic_visit(node)

    def visit_Expr(self, node):
        if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                and node.value.func.id == ASSIGN_NAME):
            return None
        return self.generic_visit(node)


def instrument(function_node, namespace, capture_value, capture_assignment, filename):
    """Compile only the supplied bound function; no data calls occur here.

    capture_value(id, value, locals) and capture_assignment(marker, locals) must
    only copy values for exact target keys. Exceptions propagate and stop output.
    """
    original = copy.deepcopy(function_node)
    if any(isinstance(node, ast.Name) and node.id in (VALUE_NAME, ASSIGN_NAME)
           for node in ast.walk(original)):
        raise RuntimeError("OBSERVER_RESERVED_NAME_COLLISION")
    transform = ValueObserverTransform(original.name)
    changed = transform.visit(copy.deepcopy(original))
    restored = RemoveObserver().visit(copy.deepcopy(changed))
    if ast.dump(restored, include_attributes=False) != ast.dump(original, include_attributes=False):
        raise RuntimeError("OBSERVER_STRIP_AST_NOT_EXACT")

    def value_wrapper(identity, value, local_values):
        capture_value(transform.entries[identity], value, local_values)
        return value

    def assignment_wrapper(marker, local_values):
        capture_assignment(json.loads(marker), local_values)
        return None

    # A separate namespace per source function prevents observer metadata clash.
    local_namespace = dict(namespace)
    local_namespace[VALUE_NAME] = value_wrapper
    local_namespace[ASSIGN_NAME] = assignment_wrapper
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        changed], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), filename, "exec"), local_namespace)
    return local_namespace[original.name], dict(
        original_ast_sha256=ast_sha(original),
        stripped_ast_sha256=ast_sha(restored),
        instrumented_ast_sha256=ast_sha(changed),
        expressions=transform.entries,
        returned_objects_unchanged=True,
        data_or_score_calls_in_instrument=0)
