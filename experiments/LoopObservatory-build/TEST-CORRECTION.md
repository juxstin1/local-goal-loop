# Test correction and environment observations

The first added usability test searched only descendants of the Observatory
Frame for a label bound to summary_var. Qwen placed a correctly bound label under
the root window instead. The product requirement was to display the summary, so
that test was too restrictive. After DESKTOP-REPAIR finished, the host changed the
search from descendants(app) to descendants(root). The check still requires a
managed widget bound to the correct variable. The original test_core.py and
test_desktop.py were never changed. Earlier test hashes and receipts are retained.

Other interface failures were implementation problems: stale detail after loading
an empty file; duplicated parser ignoring repaired core behavior; selection
destroying role colors; and fixed scroll bounds hiding later cards. Additional
checks for parser parity, preserved colors, and all 30 cards being reachable were
added before DESKTOP-FINAL.

Tcl initialization intermittently failed when pytest created several Tk roots in
one process, both inside and outside the sandbox. These errors are recorded as
environment/test-execution failures, not as model implementation failures.
