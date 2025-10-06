from gettext import gettext

import click


class FullHelpGroup(click.Group):
    def format_commands(
        self, ctx: click.Context, formatter: click.HelpFormatter
    ) -> None:
        """Extra format methods for multi methods that adds all the commands
        after the options.
        """
        commands: list[tuple[str, click.Command]] = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None:
                continue
            if cmd.hidden:
                continue

            commands.append((subcommand, cmd))

        if commands:
            rows: list[tuple[str, str]] = []
            for subcommand, cmd in commands:
                help_str = cmd.help if cmd.help is not None else ""
                rows.append((subcommand, help_str))

            if rows:
                with formatter.section(gettext("Commands")):
                    formatter.write_dl(rows)
