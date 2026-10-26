# Setup guide (Phase 0)

Everything below happens on your PC. Claude has already done the rest:
created this project folder, written the first in-game script and the Python
connection test, and added this project's `lua` folder to DFHack's script paths.

Total time: about 20 minutes.

---

## Step 1 — Check the game can see our scripts (2 min)

Claude added this line to
`D:\SteamLibrary\steamapps\common\Dwarf Fortress\dfhack-config\script-paths.txt`:

```
+C:\Users\skulr\Documents\DF-AI\lua
```

DFHack only reads that file when the game starts, so:

1. **Quit Dwarf Fortress completely**, then start it again from the **DFHack** entry in Steam.
2. Load your fort.
3. Open the DFHack launcher (the DFHack logo button in the corner, or the backtick key `` ` ``).
4. Type `ai-ping` and press Enter.

You should see one line of text starting with `{"bridge":"ai-ping"` that includes
`"citizens":194`. If it says the command isn't found, tell Claude.

## Step 2 — Install Python (5 min)

1. Go to https://www.python.org/downloads/ and click the big yellow **Download Python 3.x** button.
2. Run the installer. **On the first screen, tick "Add python.exe to PATH"** before clicking Install Now.
   This is the step people most often miss.
3. Open a **new** PowerShell window and type:
   ```
   python --version
   ```
   It should print `Python 3.something`. If it opens the Microsoft Store instead, the PATH box
   wasn't ticked: re-run the installer, choose Modify, and tick it.

## Step 3 — Run the connection test (2 min)

With DF running and your fort loaded, in PowerShell:

```
cd $HOME\Documents\DF-AI
python brain\check_connection.py
```

You should see something like:

```
Connected to the game.
  DFHack version : 53.16-r3
  DF version     : 53.16 ...
  Citizens       : 194
  Year           : ...

Round trip over 5 calls: median 80 ms, worst 120 ms
```

Send Claude the whole output. The round-trip number decides how often the AI can check on the fort.

## Step 4 — Set up VS Code for this project (5 min)

You already seem to have VS Code installed. If not, get it from https://code.visualstudio.com/.

1. In File Explorer, go to `Documents\DF-AI` and double-click **`DF-AI.code-workspace`**.
   It opens the project in VS Code with its settings. (Use this file to open the project from now on.)
2. A popup will offer the **recommended extensions** for this workspace. Click **Install**.
   They are *Lua* (by sumneko) and *Python* (by Microsoft).
   If the popup doesn't appear, open the Extensions panel (Ctrl+Shift+X) and type `@recommended`.
3. Open `lua\ai-ping.lua`. Hovering over `dfhack.getDFHackVersion` should show help, and words
   like `df` and `dfhack` should not be underlined as errors. That means the editor knows DFHack's Lua.

## Step 5 — Back up a test save (5 min)

The AI will make mistakes while we build it, so we test on copies.

1. In DF, **save the game** (from the Esc menu) and go back to the title screen.
2. Find the save folder. On this PC it is:
   ```
   D:\SteamLibrary\steamapps\common\Dwarf Fortress\save
   ```
   (On other PCs it can be `%APPDATA%\Bay 12 Games\Dwarf Fortress\save`,
   depending on DF's "portable mode" setting.)
3. Inside are folders named like `region1`, `region2`: one per world. Pick the one holding
   your 194-citizen fort (the most recently changed one, if you're not sure).
4. **Copy** (don't move) that folder into `Documents\DF-AI\saves\` and rename the copy
   `fixture-established`.

Later, add a fresh embark (`fixture-embark`) and, if one ever happens, a fort in crisis
(`fixture-crisis`). See `saves\README.md`.

---

When steps 1 and 3 work, Phase 0 is done and we can start Phase 1: the bridge that gives
the AI a full picture of the fort.
