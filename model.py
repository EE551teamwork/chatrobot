﻿import tensorflow as tf
from seq2seq import embedding_attention_seq2seq
class Seq2SeqModel():

    def __init__(self, source_vocab_size, target_vocab_size, en_de_seq_len, hidden_size, num_layers,
                 batch_size, learning_rate, num_samples=1024,
                 forward_only=False, beam_search=True, beam_size=10):
        '''
        Initialize and create a model
        :param source_vocab_size:input vocab size of encoder
        :param target_vocab_size: input vocab size of dncoder
        :param en_de_seq_len: maximum length of source and destination sequences
        :param hidden_size: the number of hidden layer units in the RNN model
        :param num_layers: the number of RNN stacks
        :param batch_size: batch size
        :param learning_rate
        :param num_samples: the number of sampled softmax samples when conputing loss
        :param forward_only: specify as true when predicting
        :param beam_search: apply greedy search or beam search when predicting
        :param beam_size: beam search size
        '''
        self.source_vocab_size = source_vocab_size
        self.target_vocab_size = target_vocab_size
        self.en_de_seq_len = en_de_seq_len
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.batch_size = batch_size
        self.learning_rate = tf.Variable(float(learning_rate), trainable=False)
        self.num_samples = num_samples
        self.forward_only = forward_only
        self.beam_search = beam_search
        self.beam_size = beam_size
        self.global_step = tf.Variable(0, trainable=False)

        output_projection = None
        softmax_loss_function = None
        # define the sample loss function to input into sequence_loss_by_example funcion
        if num_samples > 0 and num_samples < self.target_vocab_size:
            w = tf.get_variable('proj_w', [hidden_size, self.target_vocab_size])
            w_t = tf.transpose(w)
            b = tf.get_variable('proj_b', [self.target_vocab_size])
            output_projection = (w, b)
            #call sampled_softmax_loss function to compute sample loss
            def sample_loss(logits, labels):
                labels = tf.reshape(labels, [-1, 1])
                return tf.nn.sampled_softmax_loss(w_t, b, labels=labels, inputs=logits, num_sampled=num_samples, num_classes=self.target_vocab_size)
            softmax_loss_function = sample_loss

        self.keep_drop = tf.placeholder(tf.float32)
        # define multilayer dropout RNNCell of encoder and decoder
        def create_rnn_cell():
            encoDecoCell = tf.contrib.rnn.BasicLSTMCell(hidden_size)
            encoDecoCell = tf.contrib.rnn.DropoutWrapper(encoDecoCell, input_keep_prob=1.0, output_keep_prob=self.keep_drop)
            return encoDecoCell
        encoCell = tf.contrib.rnn.MultiRNNCell([create_rnn_cell() for _ in range(num_layers)])

        # define input placeholder
        self.encoder_inputs = []
        self.decoder_inputs = []
        self.decoder_targets = []
        self.target_weights = []
        for i in range(en_de_seq_len[0]):
            self.encoder_inputs.append(tf.placeholder(tf.int32, shape=[None, ], name="encoder{0}".format(i)))
        for i in range(en_de_seq_len[1]):
            self.decoder_inputs.append(tf.placeholder(tf.int32, shape=[None, ], name="decoder{0}".format(i)))
            self.decoder_targets.append(tf.placeholder(tf.int32, shape=[None, ], name="target{0}".format(i)))
            self.target_weights.append(tf.placeholder(tf.float32, shape=[None, ], name="weight{0}".format(i)))

        # test model, take the output of the previous moment as input for the next moment
        if forward_only:
            if beam_search:#if it is beam_search, call embedding_attention_seq2seq rather than legacy_seq2seq fuction
                self.beam_outputs, _, self.beam_path, self.beam_symbol = embedding_attention_seq2seq(
                    self.encoder_inputs, self.decoder_inputs, encoCell, num_encoder_symbols=source_vocab_size,
                    num_decoder_symbols=target_vocab_size, embedding_size=hidden_size,
                    output_projection=output_projection, feed_previous=True)
            else:
                decoder_outputs, _ = tf.contrib.legacy_seq2seq.embedding_attention_seq2seq(
                    self.encoder_inputs, self.decoder_inputs, encoCell, num_encoder_symbols=source_vocab_size,
                    num_decoder_symbols=target_vocab_size, embedding_size=hidden_size,
                    output_projection=output_projection, feed_previous=True)
                # because output_projection in seq2seq model is not defined, we need do output_projection after output
                if output_projection is not None:
                    self.outputs = tf.matmul(decoder_outputs, output_projection[0]) + output_projection[1]
        else:
            # because it is not necessary to use output as the input for the next moment, so do not use output_projection
            decoder_outputs, _ = tf.contrib.legacy_seq2seq.embedding_attention_seq2seq(
                self.encoder_inputs, self.decoder_inputs, encoCell, num_encoder_symbols=source_vocab_size,
                num_decoder_symbols=target_vocab_size, embedding_size=hidden_size, output_projection=output_projection,
                feed_previous=False)
            self.loss = tf.contrib.legacy_seq2seq.sequence_loss(
                decoder_outputs, self.decoder_targets, self.target_weights, softmax_loss_function=softmax_loss_function)

            # Initialize the optimizer
            opt = tf.train.AdamOptimizer(learning_rate=self.learning_rate, beta1=0.9, beta2=0.999, epsilon=1e-08)
            self.optOp = opt.minimize(self.loss)

        self.saver = tf.train.Saver(tf.all_variables())

    def step(self, session, encoder_inputs, decoder_inputs, decoder_targets, target_weights, go_token_id):
        #input a batch of data and train the corresponding model
        # constructing feed_inpits when sess.run
        feed_dict = {}
        if not self.forward_only:
            feed_dict[self.keep_drop] = 0.5
            for i in range(self.en_de_seq_len[0]):
                feed_dict[self.encoder_inputs[i].name] = encoder_inputs[i]
            for i in range(self.en_de_seq_len[1]):
                feed_dict[self.decoder_inputs[i].name] = decoder_inputs[i]
                feed_dict[self.decoder_targets[i].name] = decoder_targets[i]
                feed_dict[self.target_weights[i].name] = target_weights[i]
            run_ops = [self.optOp, self.loss]
        else:
            feed_dict[self.keep_drop] = 1.0
            for i in range(self.en_de_seq_len[0]):
                feed_dict[self.encoder_inputs[i].name] = encoder_inputs[i]
            feed_dict[self.decoder_inputs[0].name] = [go_token_id]
            if self.beam_search:
                run_ops = [self.beam_path, self.beam_symbol]
            else:
                run_ops = [self.outputs]

        outputs = session.run(run_ops, feed_dict)
        if not self.forward_only:
            return None, outputs[1]
        else:
            if self.beam_search:
                return outputs[0], outputs[1]