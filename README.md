AgentOS
AgentOS is the kernelized runtime inside this repository. The design target is not "many agents talking to each other", but "a Linux-like execution substrate that can host a harness-agent ecosystem safely".

Current kernelized pieces
AgentKernel: the control plane for scheduling, process lifecycle, checkpoints, IPC wakeups, and event emission.
AgentProcess: the process model for each harness agent instance, with priority, state, namespace, quota, parent linkage, and failure state.
UnitManager: a systemd-like layer that turns core phases into first-class units with templates, dependencies, restart policies, and unit-level state.
TargetManager: a target/DAG orchestration layer that groups units into activation goals, tracks target dependencies, and drives dependency-triggered auto activation.
SyscallBroker: the only sanctioned path from a harness agent to tools and kernel actions such as spawn_agent, join_process, pump_scheduler, await_ipc_message, and restore_checkpoint.
AgentNamespace: per-process visibility for repo mounts, memory mounts, tool allowlists, identity, and network access.
ResourceQuota: cgroup-like budgets for tokens, tool calls, child agents, and retries.
TaskStore: durable state in SQLite plus a mirrored runtime artifact tree under the Agent VFS mounts.
Implemented Linux mappings
process -> AgentProcess
scheduler -> AgentScheduler + priority classes
syscall -> SyscallBroker
namespace -> AgentNamespace
cgroup -> ResourceQuota
checkpoint/restart -> persisted checkpoints + restore flow
IPC -> persisted task IPC messages + wait/wake behavior
VFS -> mounted runtime tree under .agent_state
systemd/unit -> persisted task_units with template-driven execution and restart policy
systemd/target -> persisted task_targets with dependency-aware activation and DAG state
Harness species
router
retriever
planner
executor
critic
verifier
compressor
archivist
Each one is a harness agent, not a bare model call.

First-class units
Core phases now execute through unit templates instead of only ad hoc process spawns:

router.service
retriever.service
planner.service
executor.service
critic.service
verifier.service
compressor.service
archivist.service
Runtime instances use systemd-like names:

executor@step-3-attempt-1.service
critic@step-3-attempt-1.service
verifier@step-3-attempt-1.service
Each unit tracks:

template
dependencies
template-derived after / before ordering hints
unit-level timeout_seconds
unit-level OnFailure follow-up templates
unit-level OnSuccess follow-up templates
current process binding
state
restart policy
restart attempts
summary
metadata such as step index and attempt number
First-class targets
Targets now provide a higher-level orchestration graph above units:

planning.target
step.target
completion.target
task.target
Each target tracks:

dependencies on other targets
wanted units
wanted child targets
OnSuccess successor targets
target state
summary
metadata such as phase and auto-activation intent
Targets are what let AgentOS move from "call these units in order" toward a real DAG/runtime orchestration model.

Agent VFS runtime tree
The runtime now mirrors operational state into the configured VFS mounts:

/memory/session/tasks/<task_id>/task.json
/memory/session/tasks/<task_id>/manifest.json
/memory/session/tasks/<task_id>/events.jsonl
/memory/session/tasks/<task_id>/ipc.jsonl
/memory/session/tasks/<task_id>/ipc/<message_id>.json
/memory/session/tasks/<task_id>/processes/<process_id>.json
/memory/session/tasks/<task_id>/units/<unit_name>.json
/memory/session/tasks/<task_id>/targets/<target_name>.json
/memory/session/tasks/<task_id>/target_graph.json
/memory/session/tasks/<task_id>/target_graph.mmd
/memory/archive/memories/<memory_id>.json
/checkpoints/tasks/<task_id>/*.json
/tools/output/tasks/<task_id>/_all.jsonl
/tools/output/tasks/<task_id>/<process_id>.jsonl
/evals/tasks/<task_id>/<critic|verifier>_<process_id>.json
This makes the runtime inspectable through a filesystem view instead of forcing everything through SQLite queries alone.

Operator commands
/mounts: print the configured Agent VFS mounts
/taskfs [task_id]: print the runtime artifact paths and counts for a task
/units [task_id]: print persisted unit state, process binding, restart count, and dependencies
/targets [task_id]: print persisted target state, child units, child targets, and dependencies
/unitgraph [task_id]: print the persisted Mermaid unit graph for the task
/targetgraph [task_id]: print the persisted Mermaid target/unit DAG for the task
/ps [task_id]: list process state
/events [task_id]: list kernel events
/ipc [task_id]: list IPC messages
/checkpoints [task_id]: list checkpoints
/pump [task_id]: drain READY processes for the task
/restore <checkpoint_id|process_id>: restore from checkpoint
