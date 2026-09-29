# ibroadcast-artists

Exports every artist name in your [iBroadcast](https://www.ibroadcast.com/) music library to a sorted, deduplicated text file.

Entries that name several artists at once, such as `Artist A & Artist B` or `Artist A feat. Artist B`, are written to separate files, so the main list holds single artists only.

## Requirements

- Python 3.9 or newer
- The [`ibroadcast`](https://pypi.org/project/ibroadcast/) package
- An iBroadcast account, and an app `client_id` for the first login

## Install

```bash
git clone https://github.com/bonelifer/ibroadcast-artists.git
cd ibroadcast-artists
python3 -m pip install -r requirements.txt
```

## Get a client_id

The script logs in with iBroadcast's OAuth device-code flow, which needs a `client_id`:

1. Sign in at [media.ibroadcast.com](https://media.ibroadcast.com/).
2. Open the side menu, choose **Apps**, and follow the **developer** link at the bottom.
3. Create an app and copy its `client_id`.

It is only needed until the first login succeeds. After that, the script reuses the cached token and refreshes it when it expires.

## Configure

Copy the example config and set your `client_id`:

```bash
cp config.ini.example config.ini
```

| Setting | Meaning | Default |
| --- | --- | --- |
| `client_id` | OAuth app ID from the step above | none |
| `output` | Main output file | `artists.txt` next to the script |
| `token_file` | Where the login token is cached | `.ibroadcast_token.json` next to the script |

Command-line options override `config.ini`, which overrides the defaults. `config.ini` and the token file are listed in `.gitignore`. Keep the token file private: it gives read access to your library.

## Usage

```bash
python3 ibroadcast_artists.py
```

On the first run the script prints a link and a code. Open the link, enter the code, and approve access. Later runs start straight away.

Options:

| Option | Meaning |
| --- | --- |
| `-c`, `--client-id` | OAuth `client_id`, instead of the one in `config.ini` |
| `-o`, `--output` | Main output file |
| `-t`, `--token-file` | Token cache file |
| `--config` | Config file to read (default: `config.ini` next to the script) |

Run `python3 ibroadcast_artists.py --help` for the full list.

## Output

The main file (`artists.txt` by default) lists single artists, one per line, sorted without regard to case.

Names that join several artists go to a file named after the main file plus the separator found, for example `artists-feat.txt`. Each name goes to the first match in this order:

| File | Separator |
| --- | --- |
| `artists-feat.txt` | `feat.`, `featuring`, `ft.` |
| `artists-slash.txt` | `/` |
| `artists-ampersand.txt` | `&` |
| `artists-with.txt` | `with` |
| `artists-and.txt` | `and` |
| `artists-comma.txt` | `,` |
| `artists-dash.txt` | ` - ` |
| `artists-plus.txt` | ` + ` |
| `artists-x.txt` | ` x ` |
| `artists-orch.txt` | `orch.` |

Before writing, the script drops:

- Names with a stray track number in front, like `02 Merle Haggard`, when the name without it also exists. Real names such as `38 Special` are kept.
- iBroadcast placeholders: `[no artist]`, `[traditional]`, `[unknown]`.
- Names using a curly apostrophe (`’`) when the same name with a straight apostrophe also exists.
- Names missing a space before `feat.`, like `Home Freefeat. Don McLean`, when the correctly spaced name also exists.

Apart from the placeholders, a name is only dropped when its corrected form is already in the library. The script never invents a new name.

## Contributing

Contributions are welcome!

- **Bug reports**: [Open an issue](https://github.com/bonelifer/ibroadcast-artists/issues).
- **Everything else** (questions, feature requests, ideas, general discussion): [Use Discussions](https://github.com/bonelifer/ibroadcast-artists/discussions).
- Pull requests are welcome for bug fixes or discussed features.

## Acknowledgments

- Uses the [`ibroadcast`](https://github.com/ctrueden/ibroadcast-python) Python client by Curtis Rueden.
- Code review, bug fixes, and documentation assisted by [Claude](https://www.anthropic.com/claude).

## License

This project is licensed under the **GNU General Public License v3.0**.

See [LICENSE](LICENSE) for more information.
