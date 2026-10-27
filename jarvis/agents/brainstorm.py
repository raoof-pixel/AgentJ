from .. import db, llm

GUIDE = """Brainstorm like a strategist, not a list generator.
Structure your answer:
1. **Quick take** - 2-3 lines on the real goal behind this task.
2. **Ideas** - 8-12 distinct ideas. For each: a bold name, one line on what it is, and one line on why it could work.
   Mix safe bets with a few bold ones; avoid near-duplicates.
3. **Top 3 picks** - which ideas you'd do first and why (effort vs impact).
4. **Next steps** - 3-5 concrete actions for today/this week.
"""


def run(task, ctx):
    db.log(task["id"], "Brainstorming...")
    text = llm.generate(ctx["prompt"] + "\n\n" + GUIDE, system=ctx["system"], temperature=0.9)
    return text
