---
tags:
- setfit
- sentence-transformers
- text-classification
- generated_from_setfit_trainer
widget:
- text: An employee exited the rear of a flatbed semi-trailer onto an unpaved county
    road, and fractured his left tibia and was hospitalized.
- text: An employee was standing on top of a pump truck when he slipped and fell to
    the ground. The employee suffered a skull fracture.
- text: An explosion occurred while an employee was performing work on a well head.
    He sustained burns to 60% to 80% of his body.
- text: An employee was working on the rig floor assembling a bottom hole assembly
    when a shock-sub struck the top of his right foot, damaging his pinky toe. His
    toe had to be surgically amputated from the last joint.
- text: An employee was loading a die onto a press. While maneuvering it to see if
    it was loaded correctly, the employee slipped on some oil on the floor and braced
    herself by holding onto the die. The die fell off the press and onto her right
    foot, breaking it.
metrics:
- accuracy
pipeline_tag: text-classification
library_name: setfit
inference: true
base_model: sentence-transformers/all-MiniLM-L6-v2
---

# SetFit with sentence-transformers/all-MiniLM-L6-v2

This is a [SetFit](https://github.com/huggingface/setfit) model that can be used for Text Classification. This SetFit model uses [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) as the Sentence Transformer embedding model. A [LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) instance is used for classification.

The model has been trained using an efficient few-shot learning technique that involves:

1. Fine-tuning a [Sentence Transformer](https://www.sbert.net) with contrastive learning.
2. Training a classification head with features from the fine-tuned Sentence Transformer.

## Model Details

### Model Description
- **Model Type:** SetFit
- **Sentence Transformer body:** [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- **Classification head:** a [LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) instance
- **Maximum Sequence Length:** 256 tokens
- **Number of Classes:** 2 classes
<!-- - **Training Dataset:** [Unknown](https://huggingface.co/datasets/unknown) -->
<!-- - **Language:** Unknown -->
<!-- - **License:** Unknown -->

### Model Sources

- **Repository:** [SetFit on GitHub](https://github.com/huggingface/setfit)
- **Paper:** [Efficient Few-Shot Learning Without Prompts](https://arxiv.org/abs/2209.11055)
- **Blogpost:** [SetFit: Efficient Few-Shot Learning Without Prompts](https://huggingface.co/blog/setfit)

### Model Labels
| Label | Examples                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
|:------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0     | <ul><li>'One employee was hospitalized after being struck by a tire when he was airing the tire up during his pre-drive inspection.'</li><li>'Employee was loading plastic pipes onto a utility trailer. He jumped off the trailer and broke his ankle.'</li><li>'Employee was working on a fluid end expendable pump using a torque wrench when his left ring finger got caught in between and was amputated - halfway through the nailbed.'</li></ul>                                                                                                                                                                                                                                                                                                                          |
| 1     | <ul><li>'Employee was burned from his knees up to his lower abdomen after removing the strainer for maintenance on the Scott Unit.'</li><li>'An employee was injured when the brakes on a seven-car string of loaded boxcars let loose. The cars rolled into a four-car string of empty boxcars. The impact knocked an employee off the four-car string and he fell on the ground. The employee was hospitalized for lacerations.'</li><li>"Employee was working from the derrick monkey board latching and unlatching tubing. As he was unlatching the elevator that has horns and a locking mechanism, the employee's harness got caught on the horns. The horns pulled the harness and pulled him down causing small fractures in his knees that required surgery."</li></ul> |

## Uses

### Direct Use for Inference

First install the SetFit library:

```bash
pip install setfit
```

Then you can load this model and run inference.

```python
from setfit import SetFitModel

# Download from the 🤗 Hub
model = SetFitModel.from_pretrained("setfit_model_id")
# Run inference
preds = model("An explosion occurred while an employee was performing work on a well head. He sustained burns to 60% to 80% of his body.")
```

<!--
### Downstream Use

*List how someone could finetune this model on their own dataset.*
-->

<!--
### Out-of-Scope Use

*List how the model may foreseeably be misused and address what users ought not to do with the model.*
-->

<!--
## Bias, Risks and Limitations

*What are the known or foreseeable issues stemming from this model? You could also flag here known failure cases or weaknesses of the model.*
-->

<!--
### Recommendations

*What are recommendations with respect to the foreseeable issues? For example, filtering explicit content.*
-->

## Training Details

### Training Set Metrics
| Training set | Min | Median  | Max |
|:-------------|:----|:--------|:----|
| Word count   | 11  | 44.6015 | 211 |

| Label | Training Sample Count |
|:------|:----------------------|
| 0     | 197                   |
| 1     | 581                   |

### Training Hyperparameters
- batch_size: (16, 16)
- num_epochs: (1, 1)
- max_steps: -1
- sampling_strategy: oversampling
- num_iterations: 5
- body_learning_rate: (2e-05, 1e-05)
- head_learning_rate: 0.01
- loss: CosineSimilarityLoss
- distance_metric: cosine_distance
- margin: 0.25
- end_to_end: False
- use_amp: False
- warmup_proportion: 0.1
- l2_weight: 0.01
- seed: 20260910
- eval_max_steps: -1
- load_best_model_at_end: False

### Training Results
| Epoch  | Step | Training Loss | Validation Loss |
|:------:|:----:|:-------------:|:---------------:|
| 0.0021 | 1    | 0.2278        | -               |
| 0.1027 | 50   | 0.2507        | -               |
| 0.2053 | 100  | 0.2202        | -               |
| 0.3080 | 150  | 0.2098        | -               |
| 0.4107 | 200  | 0.1905        | -               |
| 0.5133 | 250  | 0.1483        | -               |
| 0.6160 | 300  | 0.1487        | -               |
| 0.7187 | 350  | 0.1328        | -               |
| 0.8214 | 400  | 0.1126        | -               |
| 0.9240 | 450  | 0.1130        | -               |

### Framework Versions
- Python: 3.13.6
- SetFit: 1.2.0
- Sentence Transformers: 5.7.0
- Transformers: 5.15.0
- PyTorch: 2.6.0+cu124
- Datasets: 5.0.1
- Tokenizers: 0.22.2

## Citation

### BibTeX
```bibtex
@article{https://doi.org/10.48550/arxiv.2209.11055,
    doi = {10.48550/ARXIV.2209.11055},
    url = {https://arxiv.org/abs/2209.11055},
    author = {Tunstall, Lewis and Reimers, Nils and Jo, Unso Eun Seo and Bates, Luke and Korat, Daniel and Wasserblat, Moshe and Pereg, Oren},
    keywords = {Computation and Language (cs.CL), FOS: Computer and information sciences, FOS: Computer and information sciences},
    title = {Efficient Few-Shot Learning Without Prompts},
    publisher = {arXiv},
    year = {2022},
    copyright = {Creative Commons Attribution 4.0 International}
}
```

<!--
## Glossary

*Clearly define terms in order to be accessible across audiences.*
-->

<!--
## Model Card Authors

*Lists the people who create the model card, providing recognition and accountability for the detailed work that goes into its construction.*
-->

<!--
## Model Card Contact

*Provides a way for people who have updates to the Model Card, suggestions, or questions, to contact the Model Card authors.*
-->