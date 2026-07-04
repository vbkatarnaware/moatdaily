# Testing

## Automated Testing
- **Status**: None currently implemented.
- The project does not currently use an automated testing framework like `pytest` or `unittest`. 

## Manual Testing / E2E Verification
- **Testing Script**: `scripts/fill_copy_test.py`
  - A mock AI script that programmatically fills `data/copy.json` with fake but realistic post copy to allow end-to-end testing of the rendering and review stages without requiring an actual LLM invocation.
- **Workflow Verification**:
  - Run `scripts/fetch_news.py`
  - Run `scripts/filter_news.py`
  - Run `scripts/write_copy.py`
  - Run `scripts/fill_copy_test.py`
  - Run `scripts/render_post.py`
  - Run `scripts/review_post.py`
  - Run `scripts/log_to_sheets.py`
  - Visual inspection of the output in `output/posts/` and the Google Sheet.

## Quality Gate
- The `scripts/review_post.py` acts as a dynamic validation layer in production. It checks image bounds, color variations (to detect blank renders), file size, copy length, and brand compliance.
