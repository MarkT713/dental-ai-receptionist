# Security Policy

## Supported version

This portfolio repository is a demonstration project. Security fixes are applied to the current default branch.

## Reporting a vulnerability

Please open a GitHub security advisory rather than a public issue when a finding could expose credentials or sensitive information.

## Deployment warning

The demo has no authentication or role-based access control. Run it on localhost or an isolated development network. Do not expose it directly to the public internet and do not use real patient data.

## Secrets

Never commit `.env`, database files, recordings, transcripts, logs, private keys, access tokens, or telephony credentials. If a credential is accidentally committed, rotate it immediately and remove it from Git history.
