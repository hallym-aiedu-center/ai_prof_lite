# Third-Party Notices

This document lists third-party software and model assets used by
AI Professor Lite 1.0.0.

## Ditto TalkingHead

AI Professor Lite uses Ditto TalkingHead for professor-avatar video generation.

- Project: Ditto: Motion-Space Diffusion for Controllable Realtime Talking Head Synthesis
- Upstream source: https://github.com/antgroup/ditto-talkinghead
- Model checkpoints: https://huggingface.co/digital-avatar/ditto-talkinghead
- License: Apache License 2.0
- Copyright: The Ditto TalkingHead authors / Ant Group

### Included components

AI Professor Lite includes portions of the Ditto TalkingHead inference source
under:

    core/ditto-talkinghead/

The original Apache License 2.0 license file is preserved in that directory.

### Model checkpoints

Ditto model checkpoints are not distributed directly with the
AI Professor Lite source repository.

During installation, the required Ditto configuration and TensorRT model
files are downloaded from the official Ditto TalkingHead repository on
Hugging Face.

The upstream Ditto TalkingHead repository states that it is released under
the Apache License 2.0. No separate checkpoint-specific license was identified
for the model files distributed from the official repository.

### Modifications

AI Professor Lite integrates Ditto TalkingHead into its lecture-generation
pipeline and invokes it as part of professor-avatar video generation.

Unless otherwise noted, ownership of Ditto TalkingHead and its model assets
remains with their respective copyright holders.

---

Apache License 2.0:
https://www.apache.org/licenses/LICENSE-2.0