"""CLI entry point for the Asili Operations Team."""

import argparse
import sys


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Asili Operations Team - AI-powered multi-agent system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Demo command
    subparsers.add_parser(
        "demo",
        help="Run the demonstration scenario",
    )

    # Server command
    server_parser = subparsers.add_parser(
        "serve",
        help="Start the API server",
    )
    server_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    server_parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind to (default: 8080)",
    )
    server_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    if args.command == "demo":
        from asili_agents.demo import main as demo_main

        demo_main()
        return 0

    elif args.command == "serve":
        import uvicorn

        uvicorn.run(
            "asili_agents.api.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
