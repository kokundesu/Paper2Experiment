# Paper2Exp demo

An agent chat: the user says what to reproduce; the assistant turns it into a task, runs the chosen workflow (A single
agent, B fixed pipeline, D planner + workers) with the chosen model, and compares the answers with what the paper
reports. The run's message holds the live graph of agents, each with a branch of its latest steps (the step running
now is lit), the selected agent's steps beside it, and at the end a table of the results against the paper. The menu
at the top right lists every task some earlier run answered in under 10 minutes and runs the chosen one from scratch.

```bash
cd Base/demo-web && npm install && npm run build   # once, and after frontend changes
.venv/bin/p2e demo serve                           # http://127.0.0.1:8780
```

For frontend work, run `npm run dev` (port 5180, proxies `/api` to the server above) next to `p2e demo serve`.

## How a request runs

1. **Draft** (`POST /api/draft`, `demo_server.draft`): the code is the GitHub URL in the message or a downloaded
   CORE-Bench capsule; with neither, the reply is `{need: repo_url}` and the chat asks for the address (no LLM call).
   One LLM call (`p2e.demo.draft_spec`) turns the prompt into a ReproSpec with `origin.source = "user"`: a title, what
   to run, and 1–8 questions. A second one (`demo.paper_values`) reads the paper (an arXiv link in the message, else
   the first one in the README) and finds the value it reports for each question. Those values are saved beside the
   spec (`runs/demo_drafts/<id>.paper.json`), never in it, so the agents cannot copy them.
2. **Run** (`POST /api/start`): the server launches `p2e demo run <spec.json> --workflow … --model …` as a subprocess.
   The workflow versions run the spec exactly as they run CORE-Bench capsules; `corebench.finish` hands a user spec
   to `demo.finish`, which saves the answers and where each was found (provenance) but grades nothing: there is no
   ground truth. The workspace is kept so the page can show the figures the run made.
3. **Watch** (`GET /api/jobs/<key>`, polled every second): `demo_server.build_state` rebuilds the graph from the run's
   `trace.jsonl`: the root (the agent for A, the pipeline for B, the Planner for D), its children (B's roles; D's
   runtime tasks, with retries nested under the task they replace), and every agent's tool calls as steps.
4. **Compare**: each answer is shown next to the paper's value with the gap and a verdict (`demo.compare`: within 2%
   of the paper's value, or 1e-8 of it, matches; within 10% is close; else it does not match; text compares
   case-insensitively).
5. **Examples** (`GET /api/examples`, `POST /api/example`): every CORE-Bench task or demo request that some finished
   run answered in under 10 minutes, once each. Picking one makes a new user spec with the same code and questions and
   starts it with the workflow and model chosen in the chat input. A CORE-Bench example is compared with the
   benchmark's reference answers and graded by its own grader (`corebench.grade_question`); a demo request with the
   paper's values found when it was first drafted.

## Where the frontend comes from

- `src/graph/`: the multi-agent graph of `agents_multi_agent_orchestration_graph.html` (cards, badges, connectors,
  top bar), laid out from the live tree instead of eight fixed cards, with a branch of step cards under each agent
  (the root's to its right). The card and step that are working glow; clicking one shows that agent's steps beside
  the graph; the graph can go full screen.
- `src/agent-run/`: Alex's `AgentRun` panel (`apps/web/src/modules/chat/components/ui/agent-run.*`), shown in the
  run's chat message and copied as is; only the `ToolStatus` type is declared locally instead of imported from
  `@alex/shared`.
