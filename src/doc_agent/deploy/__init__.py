"""Deployment helpers — runtime adapters for specific hosting platforms.

This subpackage is *optional*: the rest of doc-agent never imports from here.
A deployment script (notebook, Databricks App entry point, etc.) imports the
adapter it needs and uses it to populate environment variables before
`doc_agent.config.settings` is constructed.
"""
