"""
cltms.py — Justification-based TMS (Simplified for Mars Habitat Lab)
====================================================================

This module implements a Truth Maintenance System.
It allows creating nodes, adding justifications (A implies B),
and handling truth propagation and retraction.

Updates:
- Implemented `add_support` to link nodes.
- Implemented `retract_assumption` with recursive un-labeling.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union, Tuple, Set

class Polarity(Enum):
    TRUE = 1
    FALSE = 2
    UNKNOWN = 3

#task 1.1
class Node:
    def __init__(self, datum, node_id):  # Added node_id here
        self.datum = datum
        self.id = node_id        # Initialize the ID
        
        # State: TRUE, FALSE, or UNKNOWN
        self.value = Polarity.UNKNOWN
        self.label = Polarity.UNKNOWN # Added label to match your LTRE usage
        
        self.justifications = [] 
        self.support = None
        self.clauses = []
        
        # Added these to support the LTRE logic in your code:
        self.assumptions = set()
        self.consequences = []
        self.supporting_justification = None

    def __repr__(self):
        # Note: Changed self.label.name to self.value.name or self.label.name
        return f"<Node:{self.id} {self.datum} ({self.label.name})>"

class Clause: 
    def __init__(self, positives, negatives):
        # Lists of Node objects
        self.positives = Polarity.TRUE  # Should be TRUE
        self.negatives = Polarity.FALSE  # Should be FALSE
        self.informant = "Rule Source or Assertion"

class Justification:
    def __init__(self, informant: Any, consequent: Node, antecedents: List[Node]):
        self.informant = informant
        self.consequent = consequent
        self.antecedents = antecedents

    def is_valid(self) -> bool:
        # A justification is valid if ALL antecedents are TRUE
        return all(node.label == Polarity.TRUE for node in self.antecedents)

    def __repr__(self):
        return f"<Justification: {self.informant}>"

class CLTMS:
    def __init__(self, title: str, debugging: bool = False, complete: bool = False, delay_sat: bool = True):
        self.title = title
        self.debugging = debugging
        self.nodes: Dict[int, Node] = {}
        self.node_counter = 0
        
    def create_node(self, datum: Any, assumption: bool = False) -> Node:
        for node in self.nodes.values():
            if node.datum == datum:
                return node
        
        self.node_counter += 1
        node = Node(datum, self.node_counter)
        self.nodes[node.id] = node
        return node

    def is_true(self, node: Node) -> bool:
        return node.label == Polarity.TRUE

    def is_false(self, node: Node) -> bool:
        return node.label == Polarity.FALSE

    def enable_assumption(self, node: Node, value: Polarity, informant: Any) -> None:
        """
        Enable an assumption. This forces the node to be TRUE/FALSE.
        """
        if informant in node.assumptions and node.label == value:
            return

        node.assumptions.add(informant)
        
        # If it wasn't already set, set it and propagate
        if node.label != value:
            node.label = value
            self.propagate(node)

    def retract_assumption(self, node: Node, informant: Any) -> None:
        """
        Retract an assumption.
        """
        if informant in node.assumptions:
            node.assumptions.remove(informant)
            
        # Re-evaluate this node.
        # If it has no other assumptions and no valid justifications, it goes UNKNOWN.
        self.re_evaluate(node)

    def add_support(self, consequent: Node, antecedents: List[Node], informant: Any) -> None:
        """
        Add a justification: Antecedents -> Consequent
        """
        just = Justification(informant, consequent, antecedents)
        consequent.supporting_justification = just # Simplify: Last one wins (or handled in re_evaluate)
        
        # Link antecedents to this justification (so we know what to update if they change)
        for ant in antecedents:
            ant.consequences.append(just)
            
        # Check if this new justification fires immediately
        if just.is_valid():
            if consequent.label != Polarity.TRUE:
                consequent.label = Polarity.TRUE
                consequent.supporting_justification = just
                self.propagate(consequent)
    def evaluate_clause(clause):
        unknowns = []
        
        for node in clause.positives:
            if node.value == Polarity.TRUE: return "SATISFIED"
            if node.value == Polarity.UNKNOWN: unknowns.append((node, Polarity.TRUE))
            
        for node in clause.negatives:
            if node.value == Polarity.FALSE: return "SATISFIED"
            if node.value == Polarity.UNKNOWN: unknowns.append((node, Polarity.FALSE))
            
        if len(unknowns) == 0:
            return "VIOLATED" # Contradiction!
            
        if len(unknowns) == 1:
            # Exactly one open literal, we can force it!
            target_node, forced_value = unknowns[0]
            return ("UNIT", target_node, forced_value)
        
        return "UNRESOLVED"
    
    def propagate(self, node: Node) -> None:
        """
        Node has changed value. Check its consequences.
        """
        if node.label != Polarity.TRUE:
            return 
            
        for just in node.consequences:
            if just.is_valid():
                cons = just.consequent
                if cons.label != Polarity.TRUE:
                    cons.label = Polarity.TRUE
                    cons.supporting_justification = just
                    self.propagate(cons)

    def re_evaluate(self, node: Node) -> None:
        """
        Check if a node should still be believed. 
        If not, set to UNKNOWN and cascade.
        """
        # 1. Is it supported by an assumption?
        if node.assumptions:
            # Stays TRUE (assuming only TRUE assumptions used in this lab)
            node.label = Polarity.TRUE
            return

        # 2. Is it supported by a valid justification?
        # Note: In a full TMS we keep a list of justifications. 
        # Here we check incoming justifications implicitly or stored.
        # For this simple lab, we rely on the specific `supporting_justification` or find one.
        
        # Simple approach: Check if its CURRENT justification is still valid
        valid_just = None
        
        # We need to find *any* valid justification coming into this node.
        # Since we didn't store a list of all incoming justifications in `Node` (only one `supporting_justification`),
        # we have a slight limitation. 
        # FIX: Let's assume for this tree structure the stored one is the primary one.
        
        if node.supporting_justification and node.supporting_justification.is_valid():
            node.label = Polarity.TRUE
            return # Still supported
            
        # 3. If neither, it becomes UNKNOWN
        if node.label != Polarity.UNKNOWN:
            node.label = Polarity.UNKNOWN
            node.supporting_justification = None
            
            # Cascade: Any justification relying on this node is now invalid.
            # We must re-evaluate the consequences of those justifications.
            for just in node.consequences:
                # The consequent of this justification might now be unsupported
                self.re_evaluate(just.consequent)

    def why(self, node: Node) -> None:
        """
        Print explanation.
        """
        if node.label == Polarity.UNKNOWN:
            print(f"  Node {node.datum} is UNKNOWN (not believed).")
            return

        if node.assumptions:
            # Print the first assumption found
            print(f"  Assumption: {list(node.assumptions)[0]} (TRUE)")
            return
            
        if node.supporting_justification:
            print(f"  Derived via: {node.supporting_justification.informant}")
            for ant in node.supporting_justification.antecedents:
                print(f"    Depends on: {ant.datum}")
                # Optional: Recurse? self.why(ant)
        else:
            print(f"  (True but reason lost/unrecorded)")
