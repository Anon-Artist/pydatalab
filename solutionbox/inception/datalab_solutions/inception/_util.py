# Copyright 2017 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Reusable utility functions.
"""

import google.cloud.ml as ml
import multiprocessing
import os

import tensorflow as tf
from tensorflow.python.lib.io import file_io


_PACKAGE_GS_URL = 'gs://cloud-datalab/packages/inception-0.1.tar.gz'
_DEFAULT_CHECKPOINT_GSURL = 'gs://cloud-ml-data/img/flower_photos/inception_v3_2016_08_28.ckpt'


def is_in_IPython():
  try:
    import IPython
    return True
  except ImportError:
    return False


def default_project():
  import datalab.context
  context = datalab.context.Context.default()
  return context.project_id


def _get_latest_data_dir(input_dir):
  latest_file = os.path.join(input_dir, 'latest')
  if not ml.util._file.file_exists(latest_file):
    raise Exception(('Cannot find "latest" file in "%s". ' +
                    'Please use a preprocessing output dir.') % input_dir)
  with ml.util._file.open_local_or_gcs(latest_file, 'r') as f:
    dir_name = f.read().rstrip()
  return os.path.join(input_dir, dir_name)


def get_train_eval_files(input_dir):
  """Get preprocessed training and eval files."""
  data_dir = _get_latest_data_dir(input_dir)
  train_pattern = os.path.join(data_dir, 'train*.tfrecord.gz')
  eval_pattern = os.path.join(data_dir, 'eval*.tfrecord.gz')
  train_files = ml.util._file.glob_files(train_pattern)
  eval_files = ml.util._file.glob_files(eval_pattern)
  return train_files, eval_files


def get_labels(input_dir):
  """Get a list of labels from preprocessed output dir."""
  data_dir = _get_latest_data_dir(input_dir)
  labels_file = os.path.join(data_dir, 'labels')
  with ml.util._file.open_local_or_gcs(labels_file, mode='r') as f:
    labels = f.read().rstrip().split('\n')
  return labels


def read_examples(input_files, batch_size, shuffle, num_epochs=None):
  """Creates readers and queues for reading example protos."""
  files = []
  for e in input_files:
    for path in e.split(','):
      files.extend(file_io.get_matching_files(path))
  thread_count = multiprocessing.cpu_count()

  # The minimum number of instances in a queue from which examples are drawn
  # randomly. The larger this number, the more randomness at the expense of
  # higher memory requirements.
  min_after_dequeue = 1000

  # When batching data, the queue's capacity will be larger than the batch_size
  # by some factor. The recommended formula is (num_threads + a small safety
  # margin). For now, we use a single thread for reading, so this can be small.
  queue_size_multiplier = thread_count + 3

  # Convert num_epochs == 0 -> num_epochs is None, if necessary
  num_epochs = num_epochs or None

  # Build a queue of the filenames to be read.
  filename_queue = tf.train.string_input_producer(files, num_epochs, shuffle)

  options = tf.python_io.TFRecordOptions(
      compression_type=tf.python_io.TFRecordCompressionType.GZIP)
  example_id, encoded_example = tf.TFRecordReader(options=options).read_up_to(
      filename_queue, batch_size)

  if shuffle:
    capacity = min_after_dequeue + queue_size_multiplier * batch_size
    return tf.train.shuffle_batch(
        [example_id, encoded_example],
        batch_size,
        capacity,
        min_after_dequeue,
        enqueue_many=True,
        num_threads=thread_count)
  else:
    capacity = queue_size_multiplier * batch_size
    return tf.train.batch(
        [example_id, encoded_example],
        batch_size,
        capacity=capacity,
        enqueue_many=True,
        num_threads=thread_count)


def override_if_not_in_args(flag, argument, args):
  """Checks if flags is in args, and if not it adds the flag to args."""
  if flag not in args:
    args.extend([flag, argument])


def loss(loss_value):
  """Calculates aggregated mean loss."""
  total_loss = tf.Variable(0.0, False)
  loss_count = tf.Variable(0, False)
  total_loss_update = tf.assign_add(total_loss, loss_value)
  loss_count_update = tf.assign_add(loss_count, 1)
  loss_op = total_loss / tf.cast(loss_count, tf.float32)
  return [total_loss_update, loss_count_update], loss_op


def accuracy(logits, labels):
  """Calculates aggregated accuracy."""
  is_correct = tf.nn.in_top_k(logits, labels, 1)
  correct = tf.reduce_sum(tf.cast(is_correct, tf.int32))
  incorrect = tf.reduce_sum(tf.cast(tf.logical_not(is_correct), tf.int32))
  correct_count = tf.Variable(0, False)
  incorrect_count = tf.Variable(0, False)
  correct_count_update = tf.assign_add(correct_count, correct)
  incorrect_count_update = tf.assign_add(incorrect_count, incorrect)
  accuracy_op = tf.cast(correct_count, tf.float32) / tf.cast(
      correct_count + incorrect_count, tf.float32)
  return [correct_count_update, incorrect_count_update], accuracy_op