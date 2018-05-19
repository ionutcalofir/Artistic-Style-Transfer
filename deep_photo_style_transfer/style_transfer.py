import cv2
import tensorflow as tf
import numpy as np
import scipy.io as sio
from scipy.sparse import csr_matrix

from conv_nets.vgg19 import VGG19
from utils import Utils

class StyleTransfer():
  def __init__(self,
      model_name='vgg19',
      content_img_height=224,
      content_img_width=224,
      content_img_channels=3,
      style_img_height=224,
      style_img_width=224,
      style_img_channels=3,
      noise_img_height=224,
      noise_img_width=224,
      noise_img_channels=3,
      content_layers=[],
      style_layers=[],
      style_layers_w=[],
      alfa=1,
      beta=1,
      gamma=1,
      learning_rate=2,
      num_iters=1000):
    self.model_name = model_name

    self.content_img_height = content_img_height
    self.content_img_width = content_img_width
    self.content_img_channels = content_img_channels
    self.style_img_height = style_img_height
    self.style_img_width = style_img_width
    self.style_img_channels = style_img_channels
    self.noise_img_height = noise_img_height
    self.noise_img_width = noise_img_width
    self.noise_img_channels = noise_img_channels

    self.content_layers = content_layers
    self.style_layers = style_layers
    self.style_layers_w = style_layers_w
    self.alfa = alfa
    self.beta = beta
    self.gamma = gamma

    self.learning_rate = learning_rate
    self.num_iters = num_iters

    # self.mask_color = {'color': [B, G, R]}
    self.mask_color = {'white': [205, 205, 205],
                       'black': [52, 52, 52],
                       'blue': [205, 52, 52],
                       'green': [52, 205, 52],
                       'red': [52, 52, 205]}
    self.mask_channels = len(self.mask_color)

  def _get_mask_img(self, mask_img_path):
    mask_img = cv2.imread(mask_img_path)
    input_mask = None

    for k, v in self.mask_color.items():
      curr_mask = np.zeros((mask_img.shape[0], mask_img.shape[1], 1), dtype=np.uint8)

      for i in range(mask_img.shape[0]):
        for j in range((mask_img.shape[1])):
          if k == 'white' \
                  and mask_img[i][j][0] > v[0] \
                  and mask_img[i][j][1] > v[1] \
                  and mask_img[i][j][2] > v[2]:
            curr_mask[i][j][0] = 1
          elif k == 'black' \
                    and mask_img[i][j][0] < v[0] \
                    and mask_img[i][j][1] < v[1] \
                    and mask_img[i][j][2] < v[2]:
            curr_mask[i][j][0] = 1
          elif k == 'blue' \
                    and mask_img[i][j][0] > v[0] \
                    and mask_img[i][j][1] < v[1] \
                    and mask_img[i][j][2] < v[2]:
            curr_mask[i][j][0] = 1
          elif k == 'green' \
                    and mask_img[i][j][0] < v[0] \
                    and mask_img[i][j][1] > v[1] \
                    and mask_img[i][j][2] < v[2]:
            curr_mask[i][j][0] = 1
          elif k == 'red' \
                    and mask_img[i][j][0] < v[0] \
                    and mask_img[i][j][1] < v[1] \
                    and mask_img[i][j][2] > v[2]:
            curr_mask[i][j][0] = 1

      if input_mask is None:
        input_mask = curr_mask
      else:
        input_mask = np.concatenate((input_mask, curr_mask), axis=2)

    return input_mask

  def _get_laplacian_matrix(self, mat_path):
    mat = sio.loadmat(mat_path)

    sp = mat['CSR']

    row_ind = sp[:, 0].astype(np.int64)
    col_ind = sp[:, 1].astype(np.int64)
    ind = []
    for i in range(len(row_ind)):
      ind.append([row_ind[i] - 1, col_ind[i] - 1]) # -1 because octave starts from 1
    val = sp[:, 2].astype(np.float32)
    h = self.content_img_height * self.content_img_width
    w = self.content_img_height * self.content_img_width

    indices = np.array(ind, dtype=np.int64)
    values = np.array(val, dtype=np.float32)
    shape = np.array([h, w], dtype=np.int64)

    return indices, values, shape

  def _get_content_loss(self, content_img_layers, noise_img_layers):
    content_loss = tf.constant(0.0)
    for content_layer_name in self.content_layers:
      content_loss = content_loss \
                     + tf.reduce_sum(tf.square(
                        content_img_layers[content_layer_name] \
                        - noise_img_layers[content_layer_name]))
      content_loss = tf.scalar_mul(1.0 / (2.0
                                   * tf.cast(tf.shape(content_img_layers[content_layer_name])[1],
                                             tf.float32)
                                   * tf.cast(tf.shape(content_img_layers[content_layer_name])[2],
                                             tf.float32)
                                   * tf.cast(tf.shape(content_img_layers[content_layer_name])[3],
                                             tf.float32)),
                                   content_loss)

    return content_loss

  def _get_style_loss(self, style_img_layers, noise_img_layers,
                            mask_style_img, mask_content_img):
    style_loss = tf.constant(0.0)

    for i, style_layer_name in enumerate(self.style_layers):
      sz = tf.constant([style_img_layers[style_layer_name].get_shape().as_list()[1],
                        style_img_layers[style_layer_name].get_shape().as_list()[2]])
      style_img = tf.image.resize_images(mask_style_img, sz)
      sz = tf.constant([noise_img_layers[style_layer_name].get_shape().as_list()[1],
                        noise_img_layers[style_layer_name].get_shape().as_list()[2]])
      content_img = tf.image.resize_images(mask_content_img, sz)
      for c in range(self.mask_channels):
        mask_matrix_style_img = tf.multiply(style_img_layers[style_layer_name],
                                            tf.reshape(style_img[:, :, :, c],
                                                       [tf.shape(style_img)[0],
                                                        tf.shape(style_img)[1],
                                                        tf.shape(style_img)[2],
                                                        1]))
        mask_matrix_noise_img = tf.multiply(noise_img_layers[style_layer_name],
                                            tf.reshape(content_img[:, :, :, c],
                                                       [tf.shape(content_img)[0],
                                                        tf.shape(content_img)[1],
                                                        tf.shape(content_img)[2],
                                                        1]))
        channels_matrix_style_img = tf.reshape(mask_matrix_style_img,
                                               [-1, tf.shape(mask_matrix_style_img)[3]])
        channels_matrix_noise_img = tf.reshape(mask_matrix_noise_img,
                                               [-1, tf.shape(mask_matrix_noise_img)[3]])

        gram_matrix_style = tf.matmul(tf.transpose(channels_matrix_style_img),
                              channels_matrix_style_img)
        gram_matrix_noise = tf.matmul(tf.transpose(channels_matrix_noise_img),
                              channels_matrix_noise_img)

        El = tf.reduce_sum(tf.square(gram_matrix_style - gram_matrix_noise))
        El = tf.scalar_mul(1.0 / (4.0
                           * tf.square(tf.cast(tf.shape(style_img_layers[style_layer_name])[1],
                                               tf.float32))
                           * tf.square(tf.cast(tf.shape(style_img_layers[style_layer_name])[2],
                                               tf.float32))
                           * tf.square(tf.cast(tf.shape(style_img_layers[style_layer_name])[3],
                                               tf.float32))),
                           El)
        style_loss = style_loss + tf.scalar_mul(self.style_layers_w[i], El)

    return style_loss

  def _get_photorealism_loss(self, laplacian_matrix, noise_img):
    photorealism_loss = tf.constant(0.0)
    for c in range(noise_img.get_shape().as_list()[3]):
      v_noise_img = tf.reshape(noise_img[:, :, :, c], [-1, 1])
      loss = tf.sparse_tensor_dense_matmul(laplacian_matrix, v_noise_img)
      loss = tf.matmul(tf.transpose(v_noise_img), loss)
      loss = tf.scalar_mul(1.0 / (2.0 * self.content_img_height * self.content_img_width),
                           tf.reduce_sum(loss))

      photorealism_loss = photorealism_loss + loss

    return photorealism_loss

  def build(self):
    tf.reset_default_graph()

    if self.model_name == 'vgg19':
      self.model = VGG19()
      self.noise_img_init = tf.truncated_normal(shape=[1,
                                                       self.noise_img_height,
                                                       self.noise_img_width,
                                                       self.noise_img_channels],
                                                mean=0.0,
                                                stddev=57.39)
    self.content_img = tf.placeholder(tf.float32, [None, self.content_img_height,
                self.content_img_width, self.content_img_channels])
    self.style_img = tf.placeholder(tf.float32, [None, self.style_img_height,
                self.style_img_width, self.style_img_channels])

    self.laplacian_matrix = tf.sparse_placeholder(tf.float32)
    self.mask_content_img = tf.placeholder(tf.float32, [None, self.content_img_height,
                self.content_img_width, self.mask_channels])
    self.mask_style_img = tf.placeholder(tf.float32, [None, self.style_img_height,
                self.style_img_width, self.mask_channels])

    self.noise_img = tf.get_variable(name='output_image',
      initializer=self.noise_img_init)
    tf.summary.histogram("noise_img", self.noise_img)
    tf.summary.image('noise_img', self.noise_img)

    _, self.content_img_layers = self.model.run(self.content_img)
    _, self.style_img_layers = self.model.run(self.style_img)
    _, self.noise_img_layers = self.model.run(self.noise_img)

    self.content_loss = self._get_content_loss(self.content_img_layers,
                                               self.noise_img_layers)
    self.style_loss = self._get_style_loss(self.style_img_layers,
                                           self.noise_img_layers,
                                           self.mask_style_img,
                                           self.mask_content_img)
    self.photorealism_loss = self._get_photorealism_loss(self.laplacian_matrix,
                                                         self.noise_img)
    self.total_loss = self.alfa * self.content_loss \
                      + self.beta * self.style_loss \
                      + self.gamma * self.photorealism_loss

    tf.summary.scalar('content_loss', self.content_loss)
    tf.summary.scalar('style_loss', self.style_loss)
    tf.summary.scalar('photorealism_loss', self.photorealism_loss)
    tf.summary.scalar('total_loss', self.total_loss)

    var_list = tf.trainable_variables()
    self.var_list = [var for var in var_list if 'output_image' in var.name]

    self.optim = tf.train.AdamOptimizer(learning_rate=self.learning_rate,
        name='adam_optimizer').minimize(self.total_loss, var_list=self.var_list)

  def train(self):
    summ = tf.summary.merge_all()
    with tf.Session() as sess:
      sess.run(tf.global_variables_initializer())

      writer = tf.summary.FileWriter('tensorboard')
      ut = Utils()

      writer.add_graph(sess.graph)

      content_img = np.reshape(ut.get_img('ionut.jpg', width=224, height=224), (1, 224, 224, 3))
      style_img = np.reshape(ut.get_img('micul_print.jpg', width=224, height=224), (1, 224, 224, 3))
      mask_content_img = self._get_mask_img('ionut_mask_resized.jpg')
      mask_content_img = np.reshape(mask_content_img,
                                    (1,
                                     mask_content_img.shape[0],
                                     mask_content_img.shape[1],
                                     mask_content_img.shape[2]))
      mask_style_img = self._get_mask_img('micul_print_mask_resized.jpg')
      mask_style_img = np.reshape(mask_style_img,
                                    (1,
                                     mask_style_img.shape[0],
                                     mask_style_img.shape[1],
                                     mask_style_img.shape[2]))
      print('Done loading mask images.')
      laplacian_matrix = \
          self._get_laplacian_matrix('deep_photo_style_transfer/gen_laplacian/ionut.mat')
      print('Done loading laplacian matrix.')

      for i in range(self.num_iters):
        _, content_loss, style_loss, photorealism_loss, out_loss, out_img =  sess.run(
              [self.optim,
               self.content_loss,
               self.style_loss,
               self.photorealism_loss,
               self.total_loss,
               self.noise_img],
              feed_dict={self.content_img: content_img,
                         self.style_img: style_img,
                         self.mask_content_img: mask_content_img,
                         self.mask_style_img: mask_style_img,
                         self.laplacian_matrix: tf.SparseTensorValue(laplacian_matrix[0],
                                                                     laplacian_matrix[1],
                                                                     laplacian_matrix[2])})

        print('it: ', i)
        print('Content loss: ', content_loss)
        print('Style loss: ', style_loss)
        print('Photorealism loss: ', photorealism_loss)
        print('Total loss: ', out_loss)

        if i % 10 == 0:
          ut.save_img(ut.denormalize_img(out_img[0]), 'images/img' + str(i) + '.jpg')

          s = sess.run(summ,
                       feed_dict={self.content_img: content_img,
                                  self.style_img: style_img,
                                  self.mask_content_img: mask_content_img,
                                  self.mask_style_img: mask_style_img,
                                  self.laplacian_matrix: tf.SparseTensorValue(laplacian_matrix[0],
                                                                              laplacian_matrix[1],
                                                                              laplacian_matrix[2])})
          writer.add_summary(s, i)