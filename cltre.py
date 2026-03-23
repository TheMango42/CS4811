"""
ltre.py — LTRE rule engine
==========================

Updates:
- `assert_fact` now accepts `dependencies` list.
- Passes dependencies to CLTMS `add_support`.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    from cltms import CLTMS, Node, Polarity
except ImportError:
    raise ImportError("cltms.py not found.")

@dataclass
class DbClass:
    form: Any
    datum: Optional[Any] = None
    facts: List['Fact'] = field(default_factory=list)

@dataclass
class Rule:
    id: int
    trigger: Any
    body: Callable[['Env', Any], None]
    name: Optional[str] = None

@dataclass
class Fact:
    id: int
    lisp_form: Any
    dbclass: DbClass

Env = Dict[str, Any]

# -----------------------------------------------------------------------------
# Unification & Substitution
# -----------------------------------------------------------------------------

def is_var(x: Any) -> bool:
    return isinstance(x, str) and x.startswith("?")

def unify(pat: Any, term: Any, env: Optional[Env] = None) -> Optional[Env]:
    if env is None: env = {}
    if pat == term: return env
    if is_var(pat):
        if pat in env: return unify(env[pat], term, env)
        new_env = env.copy(); new_env[pat] = term; return new_env
    if is_var(term):
        if term in env: return unify(pat, env[term], env)
        new_env = env.copy(); new_env[term] = pat; return new_env
    if isinstance(pat, (list, tuple)) and isinstance(term, (list, tuple)):
        if len(pat) != len(term): return None
        for p_el, t_el in zip(pat, term):
            env = unify(p_el, t_el, env)
            if env is None: return None
        return env
    return None

def subst(pat: Any, env: Env) -> Any:
    if is_var(pat):
        return subst(env[pat], env) if pat in env else pat
    if isinstance(pat, (list, tuple)):
        res = [subst(el, env) for el in pat]
        return tuple(res) if isinstance(pat, tuple) else res
    return pat

# -----------------------------------------------------------------------------
# LTRE Class
# -----------------------------------------------------------------------------

class LTRE:
    def __init__(self, title: str, debugging: bool = False):
        self.title = title
        self.debugging = debugging
        self.tms = CLTMS(title=f"TMS for {title}", debugging=debugging)
        self.dbclasses: Dict[str, DbClass] = {}
        self.rules: List[Rule] = []
        self.queue: List[Tuple[Rule, Env, Any]] = []
        self.rule_counter = 0

    def subst(self, pat: Any, env: Env) -> Any:
        return subst(pat, env)

    def get_dbclass(self, form: Any) -> DbClass:
        key = str(form)
        if key not in self.dbclasses:
            dbc = DbClass(form=form)
            dbc.datum = self.tms.create_node(form)
            self.dbclasses[key] = dbc
        return self.dbclasses[key]

    def add_rule(self, trigger: Tuple[str, Any], body: Callable[[Env, Any], None], name: str = None) -> None:
        self.rule_counter += 1
        rule = Rule(id=self.rule_counter, trigger=trigger, body=body, name=name)
        self.rules.append(rule)
        for dbc in self.dbclasses.values():
            self.try_match_rule_dbclass(rule, dbc)

    def try_match_rule_dbclass(self, rule: Rule, dbc: DbClass):
        cond, pat = rule.trigger
        env = unify(pat, dbc.form)
        if env is not None:
            node = dbc.datum
            if self.check_condition(cond, node):
                self.enqueue(rule, env, node)

    def check_condition(self, cond: str, node: Any) -> bool:
        if cond == "TRUE": return self.tms.is_true(node)
        if cond == "FALSE": return self.tms.is_false(node)
        return False

    def enqueue(self, rule: Rule, env: Env, node: Any) -> None:
        self.queue.append((rule, env, node))

    def run_rules(self) -> None:
        while self.queue:
            rule, env, node = self.queue.pop(0)
            rule.body(env, node)

    # ------------------------- Facts & TMS Interface -------------------------

    def assert_fact(self, fact: Any, just: Any = "user", dependencies: List[Any] = None) -> None:
        """
        Assert a fact.
        If 'dependencies' (list of facts) is provided, it creates a justification.
        Otherwise it treats it as an assumption (if just="user") or premise.
        """
        dbc = self.get_dbclass(fact)
        node = dbc.datum

        if dependencies:
            # It's a derived fact (Logic)
            ant_nodes = [self.get_dbclass(d).datum for d in dependencies]
            self.tms.add_support(consequent=node, antecedents=ant_nodes, informant=just)
        else:
            # It's an assumption / premise
            self.tms.enable_assumption(node, Polarity.TRUE, informant=just)

        # Propagate to rules if TRUE
        if self.tms.is_true(node):
            self.propagate_fact(dbc)

    def retract(self, fact: Any, reason: Any, quiet: bool = False) -> None:
        dbc = self.get_dbclass(fact)
        node = dbc.datum
        self.tms.retract_assumption(node, informant=reason)

    def propagate_fact(self, dbc: DbClass):
        for rule in self.rules:
            self.try_match_rule_dbclass(rule, dbc)

    def fetch(self, pattern: Any) -> List[Any]:
        results = []
        for form, dbc in self.dbclasses.items():
            env = unify(pattern, dbc.form)
            if env is not None:
                if self.tms.is_true(dbc.datum):
                    results.append(subst(pattern, env))
        return results

    def explain(self, fact: Any) -> None:
        dbc = self.get_dbclass(fact)
        self.tms.why(dbc.datum)
