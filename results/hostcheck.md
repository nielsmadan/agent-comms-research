| host | adapter | fidelity | bracketed-paste markers | submit | chunking | burst order |
|---|---|---|---|---|---|---|
| tmux | tmux-keys | 7/7 exact | absent | 0d | long: 11 reads, max 1022 B | 5/5 in order |
| tmux | tmux-paste | 7/7 exact | wrapped | 0d | long: 11 reads, max 1022 B | 5/5 in order, 5 paste regions |
| tmux | tmux-paste-retry | 7/7 exact | wrapped | 0d | long: 11 reads, max 1022 B | 5/5 in order, 5 paste regions |
| tmux | tmux-buffer | 6/7 exact; multiline newline-translated: LF arrives as CR | wrapped | 0d | long: 11 reads, max 1022 B | 5/5 in order, 5 paste regions |
| zmx | zmx-send | 7/7 exact | absent | 0d | long: 11 reads, max 1022 B | 5/5 in order |
| zmx | zmx-paste | 7/7 exact | wrapped | 0d | long: 11 reads, max 1022 B | 5/5 in order, 5 paste regions |
| zellij | zellij-write | 7/7 exact | absent | 0d | long: 10 reads, max 1022 B | 5/5 in order |
| zellij | zellij-paste | 7/7 exact | wrapped | 0d | long: 11 reads, max 1022 B | 5/5 in order, 5 paste regions |
| iterm2 | iterm2-text | 7/7 exact | absent | 0d | long: 11 reads, max 1022 B | 5/5 in order |
| iterm2 | iterm2-paste | 7/7 exact | wrapped | 0d | long: 11 reads, max 1022 B | 5/5 in order, 5 paste regions |

Host notes:
- iterm2 / iterm2-text: iterm-focus ASN:0x0-0xbe0be:/pty-1DB8B621-02D1-416D-AD1A-157BAE495A90 -> ASN:0x0-0xbe0be:/pty-1DB8B621-02D1-416D-AD1A-157BAE495A90
