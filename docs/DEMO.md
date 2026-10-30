# Recorded Forge demo

This walkthrough inspects existing evidence. It needs no API keys, model calls, GPU, physics execution or training. Use the locally prepared application and imported recordings described in the [README](../README.md); then run `npm start` and open [Forge](http://127.0.0.1:4401). If dependencies or recordings are absent, complete that setup separately before presenting.

## A three-minute walkthrough

1. **Inspect the failure.** Open [the recorded workcell](http://127.0.0.1:4401/?campaign=fg-a7f42769f2). The synchronized 3D replay compares the original incident with its reduced scene. The static inspection image is an actual MuJoCo render; the current policy uses instrumented state, not camera pixels.
2. **Open the completed diagnostic.** Select **View saved experiments**. Saved runs for this campaign appear first, with their actual status. A completed run with a planner receipt opens automatically when available. The included Nebius recording is **Obstacle height → 65.0 mm**, incident `inc-657a996d965c43a3a8f9`, bound to source `fg-a7f42769f2-e65489d5a6f28fa`. Other local experiments, including inconclusive or canceled attempts, remain available.
3. **Read the result and its limits.** The saved height intervention changes **170 mm → 65 mm** under the same frozen base checkpoint. It records **0/20 → 20/20 fresh successes**, with 20 paired rescues and no regressions. The source-seed anchor is separate. Inspect the paired interval, planner receipt and replay. This is a diagnostic scene change, not learned policy improvement or a demonstrated operating envelope.
4. **Take the evidence with you.** **Export executable incident test**, beside the selected result, downloads that run's existing evidence and reproduction package. Exporting does not rerun it. Its reproduction commands can execute physics; they are outside this inspection walkthrough.
5. **Show the release decision.** Close the drawer and open **Reports**. The independently registered comparison remains **Do not promote**: the minimized nominee achieved 297/300 shifted successes, versus 300/300 for both correction comparators. The diagnostic does not change that decision.

## Scope to keep visible

Forge's current runtime is a simulated Cartesian gantry with MuJoCo contact physics and a 650-parameter waypoint MLP. NVIDIA Nemotron Ultra on Nebius proposed the saved, reviewed height intervention. The planner explains a hypothesis; measured physics determines its outcome.

GR00T N1.7 / LIBERO integration has **seven pending qualification gates**. Expand **Inspect qualification gates** on the Workcell to inspect them. No GR00T inference, GPU execution, visual policy repair or learned GR00T improvement is claimed.

For this demo, stay in **Saved experiments**. **New experiment**, **Run paired experiment**, new campaigns and training controls initiate additional work and are unnecessary for inspecting the recording. See the [incident workflow](incident-workbench.md) for those separate operations.
