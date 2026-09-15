"""
admin/services/
================
Business logic that shouldn't live inside a route handler:
  - validation.py         : numeric/field validation rules, reused by
                             both "propose edit" and "propose new"
  - proposal_service.py    : creating proposals (this message), and
                             approving/rejecting them (added once
                             routes/proposals.py exists)

Routes stay thin: parse the request, call a service function, flash +
redirect. This is the one place to change if a validation rule or the
approval logic itself ever needs to change.
"""