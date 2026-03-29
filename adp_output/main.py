import curses

def show_message(stdscr):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    msg = "Happy Makar Sankranti"
    x = w // 2 - len(msg) // 2
    y = h // 2
    stdscr.addstr(y, x, msg)
    stdscr.refresh()
    stdscr.getch()

def main():
    curses.wrapper(show_message)

if __name__ == "__main__":
    main()