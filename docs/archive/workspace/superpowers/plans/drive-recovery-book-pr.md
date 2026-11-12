Regenerate the embedded Colab notebook to pin the Drive cleanup/recovery fix. The download cell now falls back to a raw local rescue ZIP if normal statistics export fails, and displays cleanup diagnostics when present. Final data CSVs remain unchanged.

Validation: notebook mirror provenance/code-cell checks, mirror regression test and Book build with execution. The operational Colab notebook remains nonexecuting during Book compilation. Live smoke results are pending runtime evidence.
