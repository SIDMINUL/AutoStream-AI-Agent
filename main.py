"""
main.py – CLI entry point for the AutoStream AI Sales Agent
============================================================
Run:
    python main.py
"""

from agent import initial_state, process_turn

BANNER = """
╔══════════════════════════════════════════════════════╗
║   🎬  AutoStream AI Assistant  (powered by Nova)    ║
║   Type  'quit'  or  'exit'  to end the session      ║
╚══════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    state = initial_state()

    # Opening message from Nova
    opening = (
        "Hi there! 👋 I'm Nova, AutoStream's AI assistant.\n"
        "I can help with pricing, features, or getting you signed up. "
        "What can I do for you today?"
    )
    print(f"Nova: {opening}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye! 👋")
            break

        if not user_input:
            continue

        if user_input.lower() in {"quit", "exit", "q", "bye"}:
            print("\nNova: Thanks for chatting! Have a great day 🎬")
            break

        reply, state = process_turn(user_input, state)
        print(f"\nNova: {reply}\n")

        if state.get("lead_captured"):
            print("─── Session complete: lead successfully captured! ───\n")
            break


if __name__ == "__main__":
    main()
