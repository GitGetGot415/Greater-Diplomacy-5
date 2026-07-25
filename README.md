## Greater Diplomacy 5

Greater Diplomacy 5 is an open source grand strategy game where you take control of a random country sometime between 1910 - 1950

what makes it unique is that ai controlled countries can be made to use an llm to process diplomacy, making interactions with them very immersive

feel free to look around, fork it, clone it, etc

- itch.io: https://via415.itch.io/greater-diplomacy-5 (recommended for install)
- discord: https://discord.gg/f5Jugz9SKa

## Maintaining Raw Source
if you have decided to download the raw source from here (Code > Download ZIP > extract it), this section covers how to maintain it.

**Pros:** you get every update as they are uploaded rather than getting full versions every now and then on itch.io.

**Cons:** its harder to setup (requiring git installed), although i've tried to make it as simple as it can be for you in this guide.

first, install git from https://git-scm.com/install/. the installer has a lot of options just click "next" through them, they aren't necessary.
*(p.s dont choose to download any of the extra apps & gui, just the base.)*

second, now go into your downloaded gd5 folder and run `pip install -r requirements.txt` to install all dependencies.

third, whenever you want to check if there's an update, run `git pull`. if it says "Already up to date.", you are at the latest version. If not it will
automatically upd everything to latest version on github.