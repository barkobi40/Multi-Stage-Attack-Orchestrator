import os

# מיפוי המילים להחלפה (Safe Alias -> Original Term)
REPLACEMENTS = {
    "ExecutionStage": "AttackStage",
    "WorkflowPlan": "Attack",
    "WorkflowOrchestrator": "AttackOrchestrator",
    "Workflow": "Attack"
}


def refactor_files():
    # תיקיות וקבצים לסריקה
    target_dirs = ["python_framework"]
    target_files = ["main.py"]

    files_to_process = []

    # איסוף קבצי python תחת התיקיות
    for d in target_dirs:
        if os.path.exists(d):
            for root, _, files in os.walk(d):
                for file in files:
                    if file.endswith(".py"):
                        files_to_process.append(os.path.join(root, file))

    # הוספת קבצים בודדים ברמת השורש
    for f in target_files:
        if os.path.exists(f):
            files_to_process.append(f)

    for filepath in files_to_process:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        modified = False
        for old_term, new_term in REPLACEMENTS.items():
            if old_term in content:
                content = content.replace(old_term, new_term)
                modified = True

        if modified:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[+] Refactored: {filepath}")
        else:
            print(f"[-] No changes needed: {filepath}")


if __name__ == "__main__":
    print("Starting name reversion...")
    refactor_files()
    print("Done! Remember to run python_compile or pytest to verify everything links up correctly.")