import cv2
import numpy as np
import tensorflow as tf

from utils import Utils

# google cloud
import importlib
found_module = importlib.util.find_spec(
                  'conv_nets')
if found_module is not None:
  from conv_nets.vgg19 import VGG19
  from conv_nets.transform_net import TransformNet
else:
  from vgg19 import VGG19
  from transform_net import TransformNet

class StyleTransfer():
  def __init__(self,
      model_name='vgg19',
      tensorflow_model_path='pretrained_models/vgg19/model/tensorflow/conv_wb.pkl',
      data_path='perceptual_losses_for_real_time_style_transfer/dataset',
      content_img_height=256,
      content_img_width=256,
      content_img_channels=3,
      style_img_height=256,
      style_img_width=256,
      style_img_channels=3,
      content_layers=['conv4_2'],
      style_layers=['conv1_1', 'conv2_1', 'conv3_1', 'conv4_1', 'conv5_1'],
      style_layers_w=[1.0 / 5.0, 1.0 / 5.0, 1.0 / 5.0, 1.0 / 5.0, 1.0 / 5.0],
      alfa=1,
      beta=1,
      learning_rate=0.001,
      no_epochs=2,
      batch_size=4):
    self.vgg_means = [103.939, 116.779, 123.68] # BGR
    self.model_name = model_name
    self.tensorflow_model_path = tensorflow_model_path
    self.data_path = data_path

    self.content_img_height = content_img_height
    self.content_img_width = content_img_width
    self.content_img_channels = content_img_channels
    self.style_img_height = style_img_height
    self.style_img_width = style_img_width
    self.style_img_channels = style_img_channels

    self.content_layers = content_layers
    self.style_layers = style_layers
    self.style_layers_w = style_layers_w
    self.alfa = alfa
    self.beta = beta

    self.learning_rate = learning_rate
    self.no_epochs = no_epochs
    self.batch_size = batch_size

  def _get_content_loss(self, content_layer, noise_layer):
    content_loss = tf.constant(0.0)
    content_loss = content_loss \
                   + tf.reduce_sum(tf.square(content_layer \
                                             - noise_layer))
    content_loss = tf.scalar_mul(1.0 / 2.0, content_loss)

    return content_loss

  def _get_style_loss(self, style_layer, noise_layer):
    style_loss = tf.constant(0.0)

    channels_matrix_style_img = tf.reshape(style_layer,
                                           [-1, tf.shape(style_layer)[3]])
    channels_matrix_noise_img = tf.reshape(noise_layer,
                                           [-1, tf.shape(noise_layer)[3]])

    gram_matrix_style = tf.matmul(tf.transpose(channels_matrix_style_img),
                                  channels_matrix_style_img)
    gram_matrix_noise = tf.matmul(tf.transpose(channels_matrix_noise_img),
                                  channels_matrix_noise_img)

    El = tf.reduce_sum(tf.square(gram_matrix_style - gram_matrix_noise))
    El = tf.scalar_mul(1.0 / (4.0
                       * tf.square(tf.cast(tf.shape(style_layer)[1],
                                           tf.float32))
                       * tf.square(tf.cast(tf.shape(style_layer)[2],
                                           tf.float32))
                       * tf.square(tf.cast(tf.shape(style_layer)[3],
                                           tf.float32))),
                       El)

    style_loss = style_loss + El

    return style_loss

  def build(self):
    tf.reset_default_graph()
    self.model_transform = TransformNet()

    if self.model_name == 'vgg19':
      self.model = VGG19(tensorflow_model_path=self.tensorflow_model_path)

    self.content_img_transform = tf.placeholder(tf.float32, [None, self.content_img_height,
                self.content_img_width, self.content_img_channels])
    self.content_img_vgg = tf.placeholder(tf.float32, [None, self.content_img_height,
                self.content_img_width, self.content_img_channels])
    self.style_img = tf.placeholder(tf.float32, [None, self.style_img_height,
                self.style_img_width, self.style_img_channels])

    self.noise_img = self.model_transform.run(self.content_img_transform)
    self.noise_img = (self.noise_img + 1) * 127.5 # denormalize img from transform_net

    if self.model_name == 'vgg19':
      self.noise_img = self.noise_img - self.vgg_means # normalize img for vgg19

    self.content_loss = tf.constant(0.0)
    for content_layer_name in self.content_layers:
      content_layer = self.model.run(self.content_img_vgg, content_layer_name)
      noise_layer = self.model.run(self.noise_img, content_layer_name)
      self.content_loss = self.content_loss \
                          + self._get_content_loss(content_layer, noise_layer)

    self.style_loss = tf.constant(0.0)
    for i, style_layer_name in enumerate(self.style_layers):
      style_layer = self.model.run(self.style_img, style_layer_name)
      noise_layer = self.model.run(self.noise_img, style_layer_name)
      self.style_loss = self.style_loss \
                          + tf.scalar_mul(self.style_layers_w[i],
                                self._get_style_loss(style_layer, noise_layer))

    self.total_loss = self.alfa * self.content_loss \
                      + self.beta * self.style_loss

    var_list = tf.trainable_variables()
    self.var_list = [var for var in var_list if 'transform_net' in var.name]

    self.optim = tf.train.AdamOptimizer(learning_rate=self.learning_rate,
        name='adam_optimizer').minimize(self.total_loss, var_list=self.var_list)

    tf.summary.scalar('content_loss', self.content_loss)
    tf.summary.scalar('style_loss', self.style_loss)
    tf.summary.scalar('total_loss', self.total_loss)

    tf.summary.histogram("noise_img", self.noise_img)
    tf.summary.histogram("style_img", self.style_img)
    tf.summary.histogram("content_img", self.content_img_vgg)

    tf.summary.image('noise_img', self.noise_img)

  def train(self,
            style_img_path='images/style/style1.jpg',
            output_img_path='results/plfrtst',
            tensorboard_path='tensorboard/tensorboard_plfrtst',
            model_path='models/model_freeze.ckpt'):
    saver = tf.train.Saver()
    summ = tf.summary.merge_all()
    with tf.Session() as sess:
      sess.run(tf.global_variables_initializer())

      writer = tf.summary.FileWriter(tensorboard_path)
      writer.add_graph(sess.graph)
      ut = Utils(data_path=self.data_path)

      y_batch = []
      for _ in range(self.batch_size):
        y_batch.append(ut.get_img(style_img_path,
                                  width=self.style_img_width,
                                  height=self.style_img_height))
      y_batch = np.array(y_batch).astype(np.float32)

      ep = 0
      i = 0
      while ep < self.no_epochs:
        ut = Utils(data_path=self.data_path)
        while True:
          x_batch_transform, batch_end = ut.next_batch_train(self.batch_size,
                                                             width=self.content_img_width,
                                                             height=self.content_img_height,
                                                             model='transform_net')
          x_batch_vgg = ut.normalize_img(ut.denormalize_img(x_batch_transform,
                                                            model='transform_net'))
          if batch_end == True: # end of epoch
            break

          _, content_loss, style_loss, out_loss, out_img =  sess.run(
                [self.optim, self.content_loss, self.style_loss, self.total_loss, self.noise_img],
                 feed_dict={self.content_img_transform: x_batch_transform,
                            self.content_img_vgg: x_batch_vgg,
                            self.style_img: y_batch})

          print('it: ', i)
          print('Content loss: ', content_loss)
          print('Style loss: ', style_loss)
          print('Total loss: ', out_loss)

          if i % 10 == 0:
            x_batch_transform = ut.next_batch_val(n_batch=1,
                                                  width=self.content_img_width,
                                                  height=self.content_img_height,
                                                  model='transform_net')
            out_img =  sess.run(self.noise_img,
                                feed_dict={self.content_img_transform: x_batch_transform})

            ut.save_img(ut.denormalize_img(out_img[0]),
                        output_img_path + '/img' + str(i) + '.png')
            ut.save_img(ut.denormalize_img(x_batch_transform[0], model='transform_net'),
                        output_img_path + '/img' + str(i) + 'o.png')

            s = sess.run(summ,
                         feed_dict={self.content_img_transform: x_batch_transform,
                                    self.content_img_vgg: x_batch_vgg,
                                    self.style_img: y_batch})
            writer.add_summary(s, i)
          i = i + 1
        ep = ep + 1
      saver.save(sess, model_path)