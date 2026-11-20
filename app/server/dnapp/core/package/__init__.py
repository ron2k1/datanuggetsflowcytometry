"""The only code in the app that imports datanuggets. Every feature reaches the package through
these modules, one per job: runtime (version, worker set-up), errors (the package's refusals as
API errors), filters, colors, flow and livecells. Each import of the package happens
inside the function that needs it, so the server starts without loading what only a worker
uses, and nothing the FastAPI process calls here imports matplotlib or datanuggets.plot."""
