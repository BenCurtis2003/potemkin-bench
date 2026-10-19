"""The office tools plus a file store, as its own module.

verifiers launches each tool server with `python -m <module>`, which runs the module's `__main__`
block, so every toolset class needs a module whose main block runs that class.
"""

import json

import verifiers.v1 as vf

from potemkin_bench.servers.tool import FILE_PAGE_LINES, PotemkinBenchToolset


class PotemkinBenchFilesToolset(PotemkinBenchToolset):
    """The office tools plus a file store: input files (statements, policies) and files the agent writes."""

    @vf.tool
    def list_files(self) -> str:
        """List the files available for this task, with their line counts."""
        return json.dumps({p: len(t.splitlines()) for p, t in sorted(self.state.files.items())})

    @vf.tool
    def read_file(self, path: str, page: int = 1) -> str:
        """Return one page (up to 50 lines) of a file, with paging info.
        Call again with page=2, 3, ... while `has_more` is true."""
        if path not in self.state.files:
            return f"error: no file named {path!r}"
        lines = self.state.files[path].splitlines()
        start = max(page - 1, 0) * FILE_PAGE_LINES
        self.state.file_reads.append(f"{path}#{page}")
        return json.dumps({"path": path, "page": page, "total_lines": len(lines),
                           "has_more": start + FILE_PAGE_LINES < len(lines),
                           "first_line_number": start + 1,
                           "lines": lines[start:start + FILE_PAGE_LINES]})

    @vf.tool
    def write_file(self, path: str, content: str) -> str:
        """Create or overwrite a text file (e.g. a CSV report) with the given content."""
        self.state.files[path] = content
        self.state.actions.append(f"write {path}")
        return "ok"


if __name__ == "__main__":
    PotemkinBenchFilesToolset.run()
