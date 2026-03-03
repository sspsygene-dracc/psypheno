- run more verification and new data generation agents --- skip those that we already verified in the aborted run

- make the run_llm_search.py generation exitable by ctrl-c, verifying that all subprocess agents are killed

- make sure subprocess agents have a timeout. Timeout should be 600 seconds.

- Finish conversion of run_llm_search as a main.py cli command.
