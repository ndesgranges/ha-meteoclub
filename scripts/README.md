# Scripts

## Setup

This repository features a ready-to-dev environment using vscode `.devcontainer.json`
This allows creating a docker container with everything ready for development

At container creation, the script `scripts/setup` is ran.

## Develop

The script `scripts/develop` launches Home Assistant

## Copy

The script `scripts/cp` allows copying the card in the `config/` directory of Home Assistant
so it can be accessed in there. With option `--all` it also copies the
integration