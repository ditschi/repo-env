
# Issues Found When Testing

## 1. File Duplication and Lockfiles
* **Duplicated Files:** Running `renv create xxx -s . -d _worktrees/ -b feature/fix-pipeline -i "*dummy*"` creates a `_worktrees/ado` directory containing what appears to be duplicated configuration files (`.repoenv.json`, `.repoenv.json.lock`, `.repoenv.marker.json`, `.repoenv.marker.json.lock`). Can we combine the marker file and the other configuration file into one?
* **Empty Lockfiles:** What is the exact purpose of the lockfile, and why does it have no content?
  * If it is intended to prevent parallel access, why isn't it removed when no operations are currently running?
  * It should ideally contain information about which process locked it, so we can instruct the user to check and kill the blocking process if necessary.

## 2. Directory Structure and Environment Resolution
* **Unexpected Worktree Location:** I expected the command to create a `_worktrees/ado/some_dummy_repo` folder containing the actual files of the worktree, but the structure looks different.
* **Defaulting to Last Used Environment:** When running a command like `renv run -- pwd` without specifying an environment, I expected the tool to automatically use the last created or last used `renv` environment.
* **Context-Aware Execution:** If the current working directory (CWD) is inside an `renv` folder, the tool should automatically use that local `renv` environment instead of the globally active one (and ideally notify the user).

## 3. Missing Flags and Commands
* **Missing `--source` Flag for `add`:** The `renv add` command is missing the `-s` / `--source` flag. It should behave the same as the `create` command, where the default source is always the current working directory.
* **Activation Logic Needed:** We need an `renv activate <name>` command that sets the current `renv` environment when none is specified.
  * Commands like `create` and `add` should hint the user to run `activate` if no environment is currently active.
  * The `create` command should also include an `--activate` flag, similar to what `add` needs.
* **Configuration Command:** We need a command to list or show the current configuration (e.g., `renv config`), similar to how `git config` works.

## 4. Usability and Auto-completion
* **Manual Deletions Ignored:** Deleting the `_worktrees/ado` directory manually from the disk is not detected by the tool. If I try to recreate it, it fails:
  ```bash
  renv create ado -s . -d _worktrees/ -b feature/RAGVII-55055-fix-pipeline-creation -i "*syno*"
  # error: Environment 'ado' already exists.
  ```
* **Auto-fallback for Typos:** When making a typo (e.g., typing `renv staus` instead of `status`), it throws an error. We should add a configuration option to automatically fall back to the suggested command after a short timeout, similar to Git's behavior.
* **Broken Auto-completion:** When typing `renv status <Tab>`, the auto-completion suggests local folders in the current directory instead of providing a list of known `renv` environments.
* **List Support for Include/Exclude:** The `--exclude` / `--include` arguments should support a comma-separated list of values (e.g., `--include "dummy-repo,*test*,this-repo"`).

## 5. Git Worktree and Branch Handling Errors
* **Robust Worktree Creation:** We need a better error handling strategy to create worktrees robustly when the `--branch` flag is omitted. Currently, it fails with:
  ```bash
  renv create ado -s . -d _worktrees/ -i "*syno*"
  # Environment 'ado' -> _worktrees/ado
  # Repositories (1): radar-synopsys-dsp-libs
  # error: git worktree add --detach _worktrees/ado/radar-synopsys-dsp-libs origin/develop failed (128):
  # fatal: '_worktrees/ado/radar-synopsys-dsp-libs' already exists
  ```
* **Handling Existing Branches:** If the target branch already exists locally, the tool should automatically use it and check it out instead of throwing an error:
  ```bash
  renv create ado -s . -d _worktrees/ -b feature/RAGVII-55055-fix-pipeline-creation -i "*syno*"
  # error: git worktree add -b feature/RAGVII-55055-fix-pipeline-creation ... failed (255):
  # fatal: A branch named 'feature/RAGVII-55055-fix-pipeline-creation' already exists.
  ```
* **Orphaned Git Worktrees:** Git still remembers old worktrees from previous script runs (even if the underlying folders were manually moved or deleted). Since a Git branch can only be checked out in one worktree at a time, this causes conflicts. We need to ensure this case is handled automatically (e.g., by running `git worktree prune` so Git recognizes the missing folders and allows us to recreate the worktree).
