#!/bin/bash

# Define output file
OUTPUT_FILE="codebase.txt"

# Define directories to search
DIRS=("." "./macos_llm_overlay")

# Find all .py files directly in specified directories (non-recursive for project root, recursive for subdir)
FILES=()

# Add Python files directly in project root
while IFS= read -r file; do
    FILES+=("$file")
done < <(find . -maxdepth 1 -type f -name "*.py")

# Add Python files inside macos_llm_overlay (recursive)
while IFS= read -r file; do
    FILES+=("$file")
done < <(find ./macos_llm_overlay -type f -name "*.py")

# Output formatted contents to the file
{
    for file in "${FILES[@]}"; do
        REL_PATH="${file#./}"   # Remove leading ./ from path
        echo "<$REL_PATH>"
        cat "$file"
        echo "</$REL_PATH>"
        echo
    done
} > "$OUTPUT_FILE"