from .. import db, llm

GUIDE = """Do the task and deliver the finished output (draft, plan, summary, etc.) ready to use.
Put the deliverable first. After it, add at most 3 short notes on choices you made or things to double-check."""


def run(task, ctx):
    db.log(task["id"], "Working on it...")
    return llm.generate(ctx["prompt"] + "\n\n" + GUIDE, system=ctx["system"], temperature=0.6)
