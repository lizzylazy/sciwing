from typing import Dict, Any, List, Optional
import copy
import torch
import pathlib
import torch.nn as nn
from torch.utils.data import DataLoader
from parsect.infer.BaseInference import BaseInference
from parsect.metrics.token_cls_accuracy import TokenClassificationAccuracy
from parsect.utils.vis_seq_tags import VisTagging
from parsect.datasets.seq_labeling.science_ie_dataset import ScienceIEDataset
from parsect.utils.science_ie_data_utils import ScienceIEDataUtils
from parsect.vocab.vocab import Vocab
from parsect.tokenizers.word_tokenizer import WordTokenizer
from parsect.tokenizers.character_tokenizer import CharacterTokenizer
from parsect.utils.tensor_utils import move_to_device
import pandas as pd


class ScienceIEInference(BaseInference):
    def __init__(
        self,
        model: nn.Module,
        model_filepath: str,
        hyperparam_config_filepath: str,
        dataset: Optional[ScienceIEDataset] = None,
    ):
        super(ScienceIEInference, self).__init__(
            model=model,
            model_filepath=model_filepath,
            hyperparam_config_filepath=hyperparam_config_filepath,
            dataset=dataset,
        )
        self.word_vocab = Vocab.load_from_file(filename=self.vocab_store_location)
        self.char_vocab = Vocab.load_from_file(filename=self.char_vocab_store_location)
        self.load_model()

        if self.test_dataset is not None:
            self.labelname2idx_mapping = self.test_dataset.get_classname2idx()
            self.idx2labelname_mapping = {
                idx: label_name
                for label_name, idx in self.labelname2idx_mapping.items()
            }
            self.ignore_indices = [
                self.labelname2idx_mapping["starting-Task"],
                self.labelname2idx_mapping["ending-Task"],
                self.labelname2idx_mapping["padding-Task"],
                self.labelname2idx_mapping["starting-Process"],
                self.labelname2idx_mapping["ending-Process"],
                self.labelname2idx_mapping["padding-Process"],
                self.labelname2idx_mapping["starting-Material"],
                self.labelname2idx_mapping["ending-Material"],
                self.labelname2idx_mapping["padding-Material"],
            ]
            self.metrics_calculator = TokenClassificationAccuracy(
                idx2labelname_mapping=self.idx2labelname_mapping
            )

            with self.msg_printer.loading("Running inference on test data"):
                self.output_analytics = self.run_inference()
            self.msg_printer.good("Finished running inference on test data")

            self.output_df = pd.DataFrame(self.output_analytics)

            num_categories = len(self.labelname2idx_mapping.keys())
            categories = [
                self.idx2labelname_mapping[idx] for idx in range(num_categories)
            ]

        self.seq_tagging_visualizer = VisTagging(tags=categories)

    def run_inference(self) -> Dict[str, Any]:
        loader = DataLoader(
            dataset=self.test_dataset, batch_size=self.batch_size, shuffle=False
        )
        output_analytics = {}
        sentences = []  # all the sentences that is seen till now
        predicted_task_tag_indices = []
        predicted_process_tag_indices = []
        predicted_material_tag_indices = []

        predicted_task_tag_names = []
        predicted_process_tag_names = []
        predicted_material_tag_names = []

        true_task_tag_indices = []
        true_process_tag_indices = []
        true_material_tag_indices = []

        true_task_tag_names = []
        true_process_tag_names = []
        true_material_tag_names = []

        for iter_dict in loader:
            iter_dict = move_to_device(iter_dict, cuda_device=self.device)

            with torch.no_grad():
                model_output_dict = self.model(
                    iter_dict, is_training=False, is_validation=False, is_test=True
                )

            self.metrics_calculator.calc_metric(
                iter_dict=iter_dict, model_forward_dict=model_output_dict
            )
            tokens = iter_dict["tokens"]
            labels = iter_dict["label"]  # N * 3T
            tokens_list = tokens.tolist()
            labels_copy = copy.deepcopy(labels)

            true_task_labels, true_process_labels, true_material_labels = torch.chunk(
                labels_copy, chunks=3, dim=1
            )

            true_task_labels_list = true_task_labels.cpu().tolist()
            true_process_labels_list = true_process_labels.cpu().tolist()
            true_material_labels_list = true_material_labels.cpu().tolist()

            batch_sentences = list(
                map(
                    self.test_dataset.word_vocab.get_disp_sentence_from_indices,
                    tokens_list,
                )
            )
            sentences.extend(batch_sentences)

            predicted_task_tags = model_output_dict["predicted_task_tags"]
            predicted_process_tags = model_output_dict["predicted_process_tags"]
            predicted_material_tags = model_output_dict["predicted_material_tags"]

            assert len(true_task_labels_list) == len(predicted_task_tags)

            predicted_task_strings = map(
                lambda tags: " ".join(
                    self.test_dataset.get_class_names_from_indices(tags)
                ),
                predicted_task_tags,
            )
            predicted_task_strings = list(predicted_task_strings)

            predicted_process_strings = map(
                lambda tags: " ".join(
                    self.test_dataset.get_class_names_from_indices(tags)
                ),
                predicted_process_tags,
            )
            predicted_process_strings = list(predicted_process_strings)

            predicted_material_strings = map(
                lambda tags: " ".join(
                    self.test_dataset.get_class_names_from_indices(tags)
                ),
                predicted_material_tags,
            )
            predicted_material_strings = list(predicted_material_strings)

            true_task_labels_strings = map(
                lambda tags: " ".join(
                    self.test_dataset.get_class_names_from_indices(tags)
                ),
                true_task_labels_list,
            )
            true_task_labels_strings = list(true_task_labels_strings)

            true_process_labels_strings = map(
                lambda tags: " ".join(
                    self.test_dataset.get_class_names_from_indices(tags)
                ),
                true_process_labels_list,
            )
            true_process_labels_strings = list(true_process_labels_strings)

            true_material_labels_strings = map(
                lambda tags: " ".join(
                    self.test_dataset.get_class_names_from_indices(tags)
                ),
                true_material_labels_list,
            )

            true_material_labels_strings = list(true_material_labels_strings)

            predicted_task_tag_indices.extend(predicted_task_tags)
            predicted_process_tag_indices.extend(predicted_process_tags)
            predicted_material_tag_indices.extend(predicted_material_tags)
            predicted_task_tag_names.extend(predicted_task_strings)
            predicted_process_tag_names.extend(predicted_process_strings)
            predicted_material_tag_names.extend(predicted_material_strings)

            true_task_tag_indices.extend(true_task_labels_list)
            true_process_tag_indices.extend(true_process_labels_list)
            true_material_tag_indices.extend(true_material_labels_list)
            true_task_tag_names.extend(true_task_labels_strings)
            true_process_tag_names.extend(true_process_labels_strings)
            true_material_tag_names.extend(true_material_labels_strings)

        output_analytics["true_task_tag_indices"] = true_task_tag_indices
        output_analytics["true_process_tag_indices"] = true_process_tag_indices
        output_analytics["true_material_tag_indices"] = true_material_tag_indices

        output_analytics["true_task_tag_names"] = true_task_tag_names
        output_analytics["true_process_tag_names"] = true_process_tag_names
        output_analytics["true_material_tag_names"] = true_material_tag_names

        output_analytics["predicted_task_tag_indices"] = predicted_task_tag_indices
        output_analytics[
            "predicted_process_tag_indices"
        ] = predicted_process_tag_indices
        output_analytics[
            "predicted_material_tag_indices"
        ] = predicted_material_tag_indices

        output_analytics["predicted_task_tag_names"] = predicted_task_tag_names
        output_analytics["predicted_process_tag_names"] = predicted_process_tag_names
        output_analytics["predicted_material_tag_names"] = predicted_material_tag_names
        output_analytics["sentences"] = sentences
        return output_analytics

    def print_prf_table(self) -> None:
        prf_table = self.metrics_calculator.report_metrics()
        print(prf_table)

    def print_confusion_matrix(self) -> None:
        self.metrics_calculator.print_confusion_metrics(
            true_tag_indices=self.output_df["true_task_tag_indices"].tolist(),
            predicted_tag_indices=self.output_df["predicted_task_tag_indices"].tolist(),
        )

        self.metrics_calculator.print_confusion_metrics(
            true_tag_indices=self.output_df["true_process_tag_indices"].tolist(),
            predicted_tag_indices=self.output_df[
                "predicted_process_tag_indices"
            ].tolist(),
        )

        self.metrics_calculator.print_confusion_metrics(
            true_tag_indices=self.output_df["true_material_tag_indices"].tolist(),
            predicted_tag_indices=self.output_df[
                "predicted_material_tag_indices"
            ].tolist(),
        )

    def get_misclassified_sentences(
        self, first_class: int, second_class: int
    ) -> List[str]:

        # get rows where true tag has first_class
        true_tag_indices = []
        pred_tag_indices = []
        true_tag_names = []
        pred_tag_names = []

        if 0 <= first_class <= 7 and 0 <= second_class <= 7:
            true_tag_indices = self.output_df.true_task_tag_indices.tolist()
            pred_tag_indices = self.output_df.predicted_task_tag_indices.tolist()
            true_tag_names = self.output_df.true_task_tag_names
            pred_tag_names = self.output_df.predicted_task_tag_names

        elif 7 < first_class <= 15 and 7 < second_class <= 15:
            true_tag_indices = self.output_df.true_process_tag_indices.tolist()
            pred_tag_indices = self.output_df.predicted_process_tag_indices.tolist()
            true_tag_names = self.output_df.true_process_tag_names
            pred_tag_names = self.output_df.predicted_process_tag_names

        elif first_class > 15 and second_class > 15:
            true_tag_indices = self.output_df.true_material_tag_indices.tolist()
            pred_tag_indices = self.output_df.predicted_material_tag_indices.tolist()
            true_tag_names = self.output_df.true_material_tag_names
            pred_tag_names = self.output_df.predicted_material_tag_names

        else:
            return ["Impossible Label combination"]

        indices = []

        for idx, (true_tag_index, pred_tag_index) in enumerate(
            zip(true_tag_indices, pred_tag_indices)
        ):
            true_tags_pred_tags = zip(true_tag_index, pred_tag_index)
            for true_tag, pred_tag in true_tags_pred_tags:
                if true_tag == first_class and pred_tag == second_class:
                    indices.append(idx)
                    break

        sentences = []

        for idx in indices:
            sentence = self.output_analytics["sentences"][idx].split()
            true_tag_labels = true_tag_names[idx].split()
            pred_tag_labels = pred_tag_names[idx].split()
            len_sentence = len(sentence)

            true_tag_labels = true_tag_labels[:len_sentence]
            pred_tag_labels = pred_tag_labels[:len_sentence]

            stylized_string_true = self.seq_tagging_visualizer.visualize_tokens(
                sentence, true_tag_labels
            )
            stylized_string_predicted = self.seq_tagging_visualizer.visualize_tokens(
                sentence, pred_tag_labels
            )

            sentence = (
                f"GOLD LABELS \n{'*' * 80} \n{stylized_string_true} \n\n"
                f"PREDICTED LABELS \n{'*' * 80} \n{stylized_string_predicted}\n\n"
            )
            sentences.append(sentence)

        return sentences

    def generate_report_for_paper(self):
        paper_report, row_names = self.metrics_calculator.report_metrics(
            report_type="paper"
        )
        return paper_report, row_names

    def infer_single_sentence(self, line: str) -> (List[str], List[str], List[str]):

        word_tokenizer = WordTokenizer(tokenizer="vanilla")
        char_tokenizer = CharacterTokenizer()
        max_word_length = self.max_length
        max_char_length = self.max_char_length
        iter_dict = ScienceIEDataset.get_iter_dict(
            line=line,
            word_vocab=self.word_vocab,
            word_tokenizer=word_tokenizer,
            max_word_length=max_word_length,
            word_add_start_end_token=False,
            char_vocab=self.char_vocab,
            char_tokenizer=char_tokenizer,
            max_char_length=max_char_length,
        )

        iter_dict = move_to_device(iter_dict, cuda_device=self.device)
        iter_dict["tokens"] = iter_dict["tokens"].unsqueeze(0)
        iter_dict["char_tokens"] = iter_dict["char_tokens"].unsqueeze(0)

        model_output_dict = self.model(
            iter_dict, is_training=False, is_validation=False, is_test=True
        )
        predicted_tags = model_output_dict["predicted_tags"]
        predicted_tags = torch.LongTensor(predicted_tags)
        task_tags, process_tags, material_tags = torch.chunk(
            predicted_tags, chunks=3, dim=1
        )
        task_tags = task_tags.squeeze().tolist()
        process_tags = process_tags.squeeze().tolist()
        material_tags = material_tags.squeeze().tolist()

        task_tag_names = [self.idx2labelname_mapping[tag_idx] for tag_idx in task_tags]
        process_tag_names = [
            self.idx2labelname_mapping[tag_idx] for tag_idx in process_tags
        ]
        material_tag_names = [
            self.idx2labelname_mapping[tag_idx] for tag_idx in material_tags
        ]

        return task_tag_names, process_tag_names, material_tag_names

    def on_user_input(self, line: str):
        words = line.split()
        words = words[: self.max_length]
        len_words = len(words)

        task_tag_names, process_tag_names, material_tag_names = self.infer_single_sentence(
            line
        )
        task_tag_names = task_tag_names[:len_words]
        process_tag_names = process_tag_names[:len_words]
        material_tag_names = material_tag_names[:len_words]

        task_tagged_string = self.seq_tagging_visualizer.visualize_tokens(
            text=words, labels=task_tag_names
        )
        process_tagged_string = self.seq_tagging_visualizer.visualize_tokens(
            text=words, labels=process_tag_names
        )
        material_tagged_string = self.seq_tagging_visualizer.visualize_tokens(
            text=words, labels=material_tag_names
        )

        display_str = (
            f"Task Labels \n {'='*20} \n {task_tagged_string} \n"
            f"Process Labels \n {'='*20} \n {process_tagged_string} \n"
            f"Material Labels \n {'='*20} \n  {material_tagged_string}"
        )
        return display_str

    def generate_predict_folder(
        self, dev_folder: pathlib.Path, pred_folder: pathlib.Path
    ):
        science_ie_data_utils = ScienceIEDataUtils(
            folderpath=dev_folder, ignore_warnings=True
        )
        file_ids = science_ie_data_utils.get_file_ids()

        for file_id in file_ids:
            with self.msg_printer.loading(
                f"Generating Science IE results for file {file_id}"
            ):
                text = science_ie_data_utils.get_text_from_fileid(file_id)
                sents = science_ie_data_utils.get_sents(text)
                try:
                    assert bool(text.split()), f"File {file_id} does not have any text"
                except AssertionError:
                    continue

                try:
                    assert len(sents) > 0
                except AssertionError:
                    continue

                conll_filepath = pred_folder.joinpath(f"{file_id}.conll")
                ann_filepath = pred_folder.joinpath(f"{file_id}.ann")
                conll_lines = []

                for sent in sents:
                    line = [token.text for token in sent]
                    line = " ".join(line)
                    task_tag_names, process_tag_names, material_tag_names = self.infer_single_sentence(
                        line=line
                    )

                    len_sent = len(sent)
                    task_tag_names = task_tag_names[:len_sent]
                    process_tag_names = process_tag_names[:len_sent]
                    material_tag_names = material_tag_names[:len_sent]

                    assert len(sent) == len(
                        task_tag_names
                    ), f"len sent: {len(sent)}, len task_tag_name: {len(task_tag_names)}"
                    assert len(sent) == len(
                        process_tag_names
                    ), f"len sent: {len(sent)}, len process_tag_names: {len(process_tag_names)}"
                    assert len(sent) == len(
                        material_tag_names
                    ), f"len sent: {len(sent)}, len material_tag_names: {len(material_tag_names)}"

                    zipped_text_tag_names = zip(
                        sent, task_tag_names, process_tag_names, material_tag_names
                    )

                    for text_tag_name in zipped_text_tag_names:
                        token, task_tag, process_tag, material_tag = text_tag_name
                        token = token.text
                        conll_line = " ".join(
                            [token, task_tag, process_tag, material_tag]
                        )
                        conll_lines.append(conll_line)

                with open(conll_filepath, "w") as fp:
                    fp.writelines("\n".join(conll_lines))
                    fp.write("\n")

                science_ie_data_utils.write_ann_file_from_conll_file(
                    conll_filepath=conll_filepath, ann_filepath=ann_filepath, text=text
                )
