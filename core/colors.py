"""Terminal color codes with a gothic/vampiric flair."""

# ANSI color codes
end = '\033[0m'
bold = '\033[1m'
red = '\033[91m'
green = '\033[92m'
yellow = '\033[93m'
blue = '\033[94m'
purple = '\033[95m'
cyan = '\033[96m'
white = '\033[97m'
dark_red = '\033[31m'
grey = '\033[90m'

# Symbolic prefixes — vampire themed
blood  = f'{red}[✦]{end} '          # success / good find
fang   = f'{purple}[⚡]{end} '       # info / progress
coffin = f'{dark_red}[☠]{end} '      # bad / error
crypt  = f'{grey}[~]{end} '          # verbose / debug
moon   = f'{cyan}[☽]{end} '          # neutral notice

# Aliases kept for internal use
good = blood
info = fang
bad  = coffin
run  = fang
