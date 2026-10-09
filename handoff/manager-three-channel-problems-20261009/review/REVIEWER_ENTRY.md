# Independent Reviewer entry

Read package and ZIP only; do not edit files or read/write business state. Review the three frozen problems in problem_matrix.md and CHAT_TASK.md. Verify facts versus CANNOT_CONFIRM, complete relevant before/after hashes, source route accuracy, no raw securities/market rows/announcement text/credentials/shared state, no algorithm/producer/deployment permission expansion, and that the reproducer is read-only.

Run PYTHONDONTWRITEBYTECODE=1 python3 tools/verify_package.py <zip>. Return REVIEWED or FAIL, P0/P1/P2, and transferability. Package review does not accept Chat repair, live API/UI behavior, deployment, or natural-session outcomes. Writer assembly is not independent review. GitHub synchronization belongs to the parent controller.
