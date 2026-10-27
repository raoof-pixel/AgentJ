from .. import db, llm

GUIDE = """Research this using current information from the web.
Answer format:
- **Answer** - the direct answer in 2-4 lines.
- **Key findings** - bullets with specific facts, numbers and dates.
- **What it means for me** - practical implications / recommended action.
Say clearly when something is uncertain or sources disagree."""


def run(task, ctx):
    db.log(task["id"], "Researching with web search...")
    return llm.generate(ctx["prompt"] + "\n\n" + GUIDE, system=ctx["system"], web_search=True, temperature=0.3)
