from cltre import LTRE
from cltms import Polarity


# =========================================================
# start the symbolic system
# =========================================================
# Initialize the Engine
eng = LTRE("Source determiner", debugging=False)

def print_separator(title):
    print(f"\n{'='*20} {title} {'='*20}")

# ---------------------------------------------------------
# Helper Function for rule making
# ---------------------------------------------------------
def make_simple_rule(trigger_pattern, logic_function, rule_name):
    """
    A helper to simplify creating rules.
    trigger_pattern: e.g., ("connected", "?x", "?y")
    logic_function: A function you write that takes (dict, engine)
    """
    def internal_rule(env, match_node):
        # Extract variables from the environment into a simple dictionary
        # e.g. {'?x': 'solar_array', '?y': 'battery'}
        variables = {k: eng.subst(k, env) for k in env}
        logic_function(variables, eng)
    
    # Updated: Removed 'name' argument to be compatible with cltre.py
    eng.add_rule(("TRUE", trigger_pattern), internal_rule)

# =========================================================
# Create mapping for different sources
# =========================================================
print_separator("PART 1: Loading Source Facts")

# defining source types
eng.assert_fact(("isa","news_article","source_type"))
eng.assert_fact(("isa","journal_article","source_type"))
eng.assert_fact(("isa","blog","source_type"))
eng.assert_fact(("isa","government","source_type"))

# difine aspects of a good source
eng.assert_fact(("isa","has_author","aspect"))
eng.assert_fact(("isa","good_url_type","aspect"))
eng.assert_fact(("isa","has_doi","aspect"))
eng.assert_fact(("isa",".org","aspect"))
eng.assert_fact(("isa",".gov","aspect"))
eng.assert_fact(("isa",".edu","aspect"))

# Define connections (connected)
eng.assert_fact(("connected","journal_article","has_doi"))
eng.assert_fact(("connected","good_url_type",".org"))
eng.assert_fact(("connected","good_url_type",".gov"))
eng.assert_fact(("connected","good_url_type",".edu"))

print("...Facts loaded.")

# =========================================================
# Create rules to determine source type
# =========================================================
print_separator("PART 2: Defining Good Source Rules")

# We want a rule: If ?s is connected to ?t, and ?s has high voltage, then ?t has high voltage.

def power_flow_logic(vars, engine):
    source = vars['?source']
    target = vars['?target']
    
    # Check if the source actually has high voltage
    # In a TMS, we look for the fact in the database.
    source_voltage_fact = ("voltage_high", source)
    
    # We query the engine to see if this fact is currently believed
    if engine.fetch(source_voltage_fact):
        print(f"RULE FIRED: Propagating power from {source} to {target}")
        
        # TODO: Assert that the target has high voltage.
        # Use ("voltage_high", target) as the fact.
        # Give it a justification so we know WHY it's on: just=("rule", "power_flow")
        
        # engine.assert_fact( ... )
        engine.assert_fact(
          ("voltage_high", target),
          just=("rule", "power_flow"),
          dependencies=[
              source_voltage_fact,
              ("connected", source, target)
          ]
          )

# Create the rule
# Trigger: Whenever we see a connection ("connected", "?source", "?target")
make_simple_rule(("connected", "?source", "?target"), power_flow_logic, "power_propagation")

print("...Rules loaded.")

# =========================================================
# PART 3: The Scenario
# =========================================================
print_separator("PART 3: Day Operations")

# The sun comes up!
sun_fact = ("voltage_high", "solar_array")
eng.assert_fact(sun_fact, just=("user", "sunshine"))

# Run the inference engine to process rules
eng.run_rules()

# Check status
target_fact = ("voltage_high", "oxygen_gen")
results = eng.fetch(target_fact)

if results:
    print(f"SUCCESS: {target_fact} is TRUE.")
    print("\nEXPLANATION (Why is it true?):")
    # Explain why the oxygen generator is on
    eng.explain(target_fact)
else:
    print(f"FAILURE: {target_fact} is NOT true. Check your rules in Part 2.")

# =========================================================
# PART 4: Truth Maintenance
# =========================================================
print_separator("PART 4: Night Operations")

print("Retracting sun_fact...")
# TODO: Retract the sun_fact.
# Hint: use eng.retract(fact, reason_used_to_assert_it)
# The reason used above was ("user", "sunshine")
eng.retract(sun_fact, ("user", "sunshine"))

# Run the engine again to settle the state
eng.run_rules()

# Verify the Oxygen Gen is now off (or at least, not believed to be on)
results_night = eng.fetch(target_fact)

if not results_night:
    print(f"SUCCESS: System correctly updated. {target_fact} is no longer believed.")
else:
    print(f"FAILURE: System still believes {target_fact}. Did you retract the sun?")
