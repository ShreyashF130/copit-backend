import os

# Files or folders to ignore
IGNORE = {'.git', 'node_modules', '__pycache__', '.DS_Store', 'venv', 'zip','Dockerfile','.env','docker-compose.yml','gitignore','.dockerignore','requirements.txt'}

def merge_codebase(output_file="codebase_summary.txt"):
    with open(output_file, 'w', encoding='utf-8') as outfile:
        for root, dirs, files in os.walk("."):
            # Filter ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE]
            
            for file in files:
                if file in IGNORE or file == output_file:
                    continue
                    
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as infile:
                        outfile.write(f"\n\n{'='*20}\n")
                        outfile.write(f"FILE: {file_path}\n")
                        outfile.write(f"{'='*20}\n\n")
                        outfile.write(infile.read())
                except (UnicodeDecodeError, PermissionError):
                    # Skip binary files or locked files
                    continue

if __name__ == "__main__":
    merge_codebase()
    print("Codebase merged into codebase_summary.txt")