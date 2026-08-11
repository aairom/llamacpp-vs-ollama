# Project Development Rule

# Project Context Guide: If Links provide here, always check the links provided here to access the source code repositories for implementation
   - llama-cpp site: https://llama-cpp.com/
   - llama-cpp site: https://llama.app/
   - llama-cpp github: https://github.com/ggml-org/llama.cpp
   - ollama site: https://ollama.com/
   - ollama github: https://github.com/ollama/ollama

# Mode change
   - You are allowed to toggle to ad-hoc and appropriate docs in regards of required tasks

# Project Structure
   - The current AGENTS.MD file overrights the global in .bob
   - All the Documents except "readme.md" should be in "Docs" folder under the parent folder
   - All the BASH scripts if needed, should be written in "scripts" folder under the parent folder
  - All bash scripts should be given run or execute rights (eg: chmod +x start.sh)

# Input folder
   - All the input documents are to be found in "input" folder under the parent folder
   - All the documents in "input" folder should be processed recurssively.

# Output folder
   - All the output documents which are asked to be provided should be writen in timestamped format in "output" folder
   - The result documents should be written in "output" folder, if the "output" folder does not exist, it should be created

# Automation Scripts:
   - All the BASH scripts, should be written in "scripts" folder under the parent folder
   - Provide a script to lauch the application in detached mode which displays the URL to access the application on the console
   - Provide a script to shutdown the application gracefully

# Documents Structure
   - The documents of the project should be created in "Docs" folder except readme.md
   - Always provide README.md with architecture + workflow diagrams as described
   - Always provide a Quickstart.md document in "Docs" folder
   - Always provide a Mermaid flow architecture for the project in the "Architecture.md" file

# Licence OpenSource
   - Always add the "Licence" type for the code in "Readme.md"

 # Git  
   - Always provide a ".gitignore" file which filters/ignores any ".env" files or any folders whichs' names start with "_" (underscore) to be pushed to GitHub (e.g.: _sources/, _images/, _docs/... ).
   - Add the following files to .gitignore if they exist in the project: *.onnx, *.onnx.data, *.so, *.tgz, *.tar.gz, *.zip, *.dylib
   - "node_modules" folder should be in .gitignore and not be sent to Github
   - In the ".gitignore" add an entry to avoid sending ".playwright-mcp" folder to remote repository

# Security
  - When building applications, never hard code the information inside the application (e.g: apiKey, email address, URL...) but provide an ".env.example" file with the variables to be saved as ".env" file to run the application 

# Unit Testing:  
  - Always test the functionnality of the code you provide 

# Document and - or code update:
   - When you make updates/enhancements and/or correct the bugs, update the existing documents and scripts, don't create new ones

# Files
   - Files in the folders which were not made by you, don't delete them

# Python Rules
   - Always provide a virtual environment for Python applications.

# Dockerfiles and container building
   - Dockerfiles should always be compatible with Containerfiles
   - Always create optimized optimized images and provide Dockerfiles which provide the smallest image sizes
   - If applicable, use multi-stage Dockerfile for removing build tools from production

# MacOS
   - On a MacOS platform, don't use the port 5000, it is reserved for the "AirDrop" application

# Local LLM
   - Ollama is locally installed

# Podman
   - Podman Desktop and Podman engines are installed

# Docker
   - Podman is used locally instead of Docker      

# Internet Search
   - If needed, search the web using the MCP servers configured   