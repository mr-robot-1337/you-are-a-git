# ⚔️ GitQuest: Master the Art of Version Control

> *"It's dangerous to code alone! Take `git init`."*

Welcome to **GitQuest** — a lightweight, zero-dependency interactive game and visual sandbox that turns learning Git from a scary terminal chore into a hands-on adventure.

Whether you've ever panicked over a detached `HEAD`, wondered where staged files actually live, or wanted a safe place to test `git reset --hard` without nuking your real project, **GitQuest** has your back!

---

## ✨ What's Inside?

* 🎮 **5 Story-Driven Levels + Free-Play Sandbox** — Progress from initializing your first repository to branching, merging, and time-traveling out of production bugs.
* 🕸️ **Live Commit DAG Visualizer** — Watch commits, parent pointers, branches (`main`, `feature`), and `HEAD` animate in real time as you type commands.
* 📦 **3-Tree State Inspector** — See files move step-by-step across the **Working Directory**, **Staging Area (Index)**, and **HEAD Commit Snapshot**.
* 💻 **Built-In Terminal + Quick-Action Buttons** — Type real commands (`git add`, `git commit`, `git checkout -b`, `git merge`, `git revert`, `git reset`) with command history (`↑`/`↓`) or click quick-fill buttons.
* ⚡ **Zero Dependencies** — Runs out of the box with pure Node.js (`http`, `fs`, `path`) or directly in any modern browser.

---

## 🚀 Quick Start

No `npm install` bloat required! Just clone or open this folder and run:

```bash
npm start
# or directly with Node:
node server.js
```

Then open **[http://localhost:3000](http://localhost:3000)** in your browser and start playing!

*(Tip: You can also set a custom port with `PORT=8080 npm start` or open `public/index.html` directly in your browser.)*

---

## 🗺️ The Campaign (Levels)

| Level | Mission Name | Skills Unlocked |
| :--- | :--- | :--- |
| **Level 1** | **Wake Up, Git!** | Initialize a repo (`git init`), create files (`touch`), and stage changes (`git add`). |
| **Level 2** | **First Snapshot** | Permanently record snapshots into the commit history (`git commit -m "..."`). |
| **Level 3** | **Branching Out** | Create isolated feature branches and move `HEAD` (`git checkout -b feature`). |
| **Level 4** | **Merging Branches** | Combine divergent histories back into `main` (`git merge feature`). |
| **Level 5** | **Oops! Undo Commit** | Rescue `main` from a bad commit using `git revert HEAD` or `git reset --hard HEAD~1`. |
| **🛠️ Sandbox** | **Free-Play Mode** | An open playground to experiment with branches, merges, resets, and commits! |

---

## 🧰 Supported Sandbox Commands

Inside the GitQuest terminal, you can mix and match shell commands and Git commands:

```bash
# File & Directory Commands
ls                          # List files in the working directory
touch <file>                # Create or update a file
edit <file> <text>          # Write custom text into a file
rm <file>                   # Remove a file
clear                       # Clear terminal output
help                        # Show all available commands

# Git Commands
git init                    # Initialize the repository
git status                  # Inspect untracked, modified, and staged files
git add <file | .>          # Move file(s) into the Staging Area (Index)
git commit -m "message"     # Create a new commit snapshot
git branch [name]           # List branches or create a new branch
git checkout [-b] <branch>  # Switch branches (or create & switch with -b)
git switch [-c] <branch>    # Switch branches (modern syntax)
git merge <branch>          # Merge target branch into current HEAD branch
git reset --hard HEAD~1     # Move current branch pointer back 1 commit
git revert HEAD             # Create a new commit that undoes the latest commit
git log                     # View commit history and branch pointers
```

---

## 📂 Project Structure

```text
.
├── package.json        # Scripts (`npm start`, `npm run dev`)
├── server.js           # Lightweight Node.js static server
├── public/
│   └── index.html      # Game UI, SVG DAG graph, and GitSandbox engine
└── README.md           # You are here!
```

---

## 🏆 Pro Tips for Players

1. **Watch the 3-Tree Inspector on the right**: Notice how `touch app.js` puts a red pill in **Working Directory**, `git add app.js` copies it into **Staging Area**, and `git commit` locks it into the **HEAD Commit Snapshot**.
2. **Compare `reset` vs `revert` in Level 5**:
   * `git reset --hard HEAD~1` rewinds the branch pointer backwards.
   * `git revert HEAD` keeps history intact and adds a brand-new commit that undoes the changes.
3. **Stuck?** Click the **↺ Reset** button at the top of the mission card anytime to start the current level fresh.

Happy branching! 🌿
