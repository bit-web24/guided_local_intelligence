# GLI Report

**Task:** how to run this project
**Model:** llama3.2:1b
**Generated:** 2026-03-13 20:01:13

---

**Running This Project**

### Step 1: Install Required Tools

The first step in running this project is to ensure that the necessary tools are installed.

* **Install `npm`**: Run `npm init`.
	+ A new file `package.json` was created in the current working directory.
	+ The basic details of the package (name, version, author) were populated into the file.
	+ Node.js version 16.14.2 was detected as the npm environment.

### Step 2: Install Git with Global Installs

Next, install `git` with global installs using:

* **Install `git` globally**: Run `npm install -g git`.

The output shows that the following command is run:
```bash
$ git --version
git version 2.30.0
```
This confirms that Git has been installed correctly on the system.

### Step 3: Initialize a New Git Repository

To create a new local repository, perform the following steps:

* **Create a `.gitconfig` file**: Open a text editor (e.g., `nano`) and add the following contents:
```markdown
[core]
 repo = .
```
* **Save and close the file**: Save and close your edited file.

This will be used to configure Git locally for future command-line operations.

### Step 4: Configure Git Locally

Configure Git to use the cloned repository by creating a new directory in the current working directory:

```bash
$ mkdir scan_repo
$ cd scan_repo
git init
```

Note that there is no code snippet in this step, rather it's a manual operation performed in the terminal.

### Step 5: Clone GitHub Repository (Optional)

If you want to clone a GitHub repository using your local `git` installation and run commands inside the cloned repository:

```bash
$ git clone https://github.com/username/repository.git
```
Make sure to replace `"username"` with your GitHub username, and `repository` with the name of the repository you wish to clone.

### Step 6: Execute Git Commands

To confirm that the local repository is working correctly and to execute commands inside it:

* **Commit changes**: Run `git add .`. To update the index and stage files.
```bash
$ git add .
$ git status
```
* **Push changes back to GitHub server**:
```bash
# in GitHub settings, note that you need to log in via GitHub and select your repository to change permissions
...
git push origin master
```

After completing these steps, make sure to test the functionality by running some commands inside your local clone or pushing a commit from `scan_repo` back to the original repository using the Git remote name (`origin`).
