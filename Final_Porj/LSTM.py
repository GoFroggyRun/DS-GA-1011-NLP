from __future__ import unicode_literals, print_function, division
from io import open
import io
import unicodedata
import string
import re
import random
import numpy as np
import torch
import torch.nn as nn
from torch import optim
from torch.autograd import Variable
from torch.utils.data import Dataset, DataLoader
import torch.nn.functional as F
from tqdm import tqdm
from collections import Counter, namedtuple
import pickle
import sacrebleu
import pandas as pd
import string
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

PAD = 0
SOS = 1
EOS = 2
UNK = 3
exclude = set(string.punctuation)

'''
https://stackoverflow.com/questions/4984647/accessing-dict-keys-like-an-attribute
'''
class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

class NMTLang:
    def __init__(self, perc_of_sent_len, input='zh', output='en', type='train', valid_vocab = None, max_vocab_size = 20000):
        if type=='train':
            self.input, self.output, self.MAX_SENT_LEN = self.drop_LongSents(self.load_pairs(input, output, type), perc_of_sent_len)
        else:
            self.input, self.output, self.MAX_SENT_LEN = self.drop_LongSents(self.load_pairs(input, output, type), None)
        if not valid_vocab:
            input_counter = self.word_count(self.input)
            output_counter = self.word_count(self.output)
            self.input_vocab = self.build_vocab(input_counter, max_vocab_size)
            self.output_vocab = self.build_vocab(output_counter, max_vocab_size)
        else:
            self.input_vocab = valid_vocab['input']
            self.output_vocab = valid_vocab['output']

    def __len__(self):
        return len(self.input)

    def __getitem__(self, idx):
        input_sent = self.input[idx]
        output_sent = self.output[idx]
        input_ids = [self.input_vocab.word2id[word] if word in self.input_vocab.word2id.keys() else self.input_vocab.word2id['<UNK>'] for word in input_sent.split(' ')]
        output_ids = [self.output_vocab.word2id[word] if word in self.output_vocab.word2id.keys() else self.output_vocab.word2id['<UNK>'] for word in output_sent.split(' ')]

        return input_sent, input_ids, output_sent, output_ids

    def load_pairs(self, lang1, lang2, type):
        if type == 'train':
            lines_1 = open('iwslt-%s-en/train.tok.%s' %(lang1, lang1) , encoding='utf-8').read().strip().split('\n')
            lines_2 = open('iwslt-%s-en/train.tok.%s' %(lang1, lang2) , encoding='utf-8').read().strip().split('\n')
        elif type == 'dev':
            lines_1 = open('iwslt-%s-en/dev.tok.%s' %(lang1, lang1) , encoding='utf-8').read().strip().split('\n')
            lines_2 = open('iwslt-%s-en/dev.tok.%s' %(lang1, lang2) , encoding='utf-8').read().strip().split('\n')
        else:
            lines_1 = open('iwslt-%s-en/test.tok.%s' %(lang1, lang1) , encoding='utf-8').read().strip().split('\n')
            lines_2 = open('iwslt-%s-en/test.tok.%s' %(lang1, lang2) , encoding='utf-8').read().strip().split('\n')
        if lang1 == 'zh':
            norm_1 = [ ' '.join([s for s in l1.split(' ') if s]) for l1 in lines_1]
            norm_2 = [ ' '.join([self.normalizeString(s) for s in re.sub(' +',' ',l2).split(' ') if s]) for l2 in lines_2]
        else:
            norm_1 = [ ' '.join([s for s in l1.split(' ') if s and s not in exclude]) for l1 in lines_1]
            norm_2 = [ ' '.join([self.normalizeString(s) for s in re.sub(' +',' ',l2).split(' ') if s]) for l2 in lines_2]
        return [[p,self.normalizeSent(q)] for p,q in zip(norm_1, norm_2)]

    def drop_LongSents(self, pairs, perc_of_sent_len):
        if perc_of_sent_len is not None:
            max_sentence_len = self.getMaxlen(pairs)
            MAX_perc = int(np.percentile(max_sentence_len, perc_of_sent_len))
            f_pairs = self.filterPairs(pairs, MAX_perc)
        else:
            MAX_perc  = self.getMaxlen(pairs)[0]
            f_pairs = self.filterPairs(pairs, MAX_perc)
        return [input[0] for input in f_pairs], [output[1] for output in f_pairs], MAX_perc

    def normalizeString(self, s):
        s = re.sub(r"&quot;", r"", s)
        s = re.sub(r"&apos;", r"", s)
        s = re.sub(r"([.!?])", r"", s)

        s = re.sub(r"([_])", r" ", s)
        s = re.sub(r"[^a-zA-Z0-9.!?]+", r"", s)
        return s

    def normalizeSent(self, sent):
        return re.sub(' +',' ',sent).strip()

    def build_vocab(self, word_count, max_vocab_size):
        vocab = AttrDict()
        vocab.word2id = {'<PAD>': PAD, '<SOS>': SOS, '<EOS>': EOS, '<UNK>': UNK}
        vocab.word2id.update({token: (ids + 4) for ids, (token, count) in enumerate(word_count.most_common(max_vocab_size))if count>=2 })
        vocab.id2word = {ids:word for word, ids in vocab.word2id.items()}
        return vocab

    def word_count(self, lan):
        count = Counter()
        for sent in lan:
            for word in sent.split(' '):
                if word: count[word] += 1
        return count

    def filterPair(self, p, MAX_len):
        return (p[0] != '') and (p[1] != '') and (len(p[0].split(' ')) <= MAX_len) and (len(p[1].split(' ')) <= MAX_len)

    def filterPairs(self, pairs, MAX_len):
        return [pair for pair in pairs if self.filterPair(pair, MAX_len)]

    def getMaxlen(self, pairs):
        return [max(len(p[0].split(' ')),len(p[1].split(' '))) for p in pairs]

    def unicodeToAscii(s):
        return ''.join(
            c for c in unicodedata.normalize('NFD', s)
            if unicodedata.category(c) != 'Mn'
        )


        def collate_fn(batch):
            batch.sort(key=lambda x: len(x[1]), reverse=True)
            _ ,input_seqs, __ , output_seqs = zip(*batch)
            input_seqs, input_lens = _padding(input_seqs)
            output_seqs, output_lens = _padding(output_seqs)

            return input_seqs.transpose(0,1), input_lens, output_seqs.transpose(0,1), output_lens

        def _padding(seqs, pad_SOS = False, pad_EOS = True):
                len_adj = int(pad_SOS) + int(pad_EOS)
                lens = [len(seq) + len_adj for seq in seqs]
                padded_seqs = torch.zeros(len(seqs), MAX_SENT_LENS + len_adj).long()
                for i, seq in enumerate(seqs):
                    p_seq = []
                    if pad_SOS: p_seq.append(SOS)
                    p_seq += seq
                    if pad_EOS: p_seq.append(EOS)
                    padded_seqs[i, :lens[i]] = torch.LongTensor(p_seq[:lens[i]])
                return padded_seqs, lens

                def collate_fn_valid(batch):
                    batch.sort(key=lambda x: len(x[1]), reverse=True)
                    _ ,input_seqs, __ , output_seqs = zip(*batch)
                    input_seqs, input_lens = _padding_valid(input_seqs)
                    output_seqs, output_lens = _padding_valid(output_seqs)

                    return input_seqs.transpose(0,1), input_lens, output_seqs.transpose(0,1), output_lens

                def _padding_valid(seqs, pad_SOS = True, pad_EOS = True):
                        len_adj = int(pad_SOS) + int(pad_EOS)
                        lens = [len(seq) + len_adj for seq in seqs]
                        padded_seqs = torch.zeros(len(seqs), MAX_SENT_LENS_VALID + len_adj).long()
                        for i, seq in enumerate(seqs):
                            p_seq = []
                            if pad_SOS: p_seq.append(SOS)
                            p_seq += seq
                            if pad_EOS: p_seq.append(EOS)
                            padded_seqs[i, :lens[i]] = torch.LongTensor(p_seq[:lens[i]])
                        return padded_seqs, lens


data = NMTLang(75, 'vi', 'en', max_vocab_size = 50000)
valid = NMTLang(None, 'vi', 'en', 'dev', {'input': data.input_vocab, 'output': data.output_vocab})
MAX_SENT_LENS = data.MAX_SENT_LEN
MAX_SENT_LENS_VALID = valid.MAX_SENT_LEN
MAX_SENT_LENS = max(data.MAX_SENT_LEN, valid.MAX_SENT_LEN)


def load_vectors_embedding(lan):
    fin = io.open('cc.%s.300.vec' %lan, 'r', encoding='utf-8', newline='\n', errors='ignore')
    if lan == 'en':
        lang = data.output_vocab
    else:
        lang = data.input_vocab
    mapping = {}
    w2v_scale = 0
    for line in fin:
        tokens = line.rstrip().split(' ')
        if tokens[0] in lang['word2id'].keys():
            mapping[tokens[0]] = map(float, tokens[1:])
            w2v_scale += np.linalg.norm(np.array(tokens[1:]))
    w2v_scale /= len(mapping)
    vocab_size = len(lang['word2id'])
    word_vec_size = 300
    embedding_mat = np.zeros((vocab_size, word_vec_size))
    count = 0

    for word, index in lang['word2id'].items():
        if word == '<PAD>': continue
        elif word in ['<SOS>', '<EOS>', '<UNK>']:
            w2v = np.random.normal(scale=w2v_scale, size=(300, ))
        elif word in mapping.keys():
            w2v = np.array([*mapping[word]])
            count += 1
        else: w2v = np.random.normal(scale=w2v_scale, size=(300, ))

        embedding_mat[index] = w2v
    print('Pretrained W2V count: {}'.format(count))

    return torch.from_numpy(embedding_mat).float()


en_w2v = load_vectors_embedding('en')
zh_w2v = load_vectors_embedding('vi')

class RNNEncoder(nn.Module):
    def __init__(self, weight = None, Freeze = True, hidden_size = 64, dropout =0, num_layers = 1):
        super(RNNEncoder, self).__init__()
        self.emb_layer = nn.Embedding(len(weight), len(weight[0]), padding_idx=PAD)
        self.emb_layer.weight.data.copy_(weight)
        if Freeze:
            self.emb_layer.weight.requires_grad = False
        self.lstm = nn.LSTM(input_size=len(weight[0]), hidden_size=hidden_size, num_layers=num_layers,
                           dropout=dropout, bidirectional=True).to(device)

    def forward(self, input, lens, hidden):
        emb_layer = self.emb_layer(input.to('cpu')).to(device)
        packed_emb = nn.utils.rnn.pack_padded_sequence(emb_layer, lens.data.tolist())
        packed_out, hn = self.lstm(packed_emb, hidden)
        unpack_out, _ =  nn.utils.rnn.pad_packed_sequence(packed_out)
        #hidden = torch.cat([hn[0:hn.size(0):2], hn[1:hn.size(0):2]], 2)
        hidden = tuple([torch.cat([h[0:h.size(0):2], h[1:h.size(0):2]], 2) for h in hn])
        return unpack_out, hidden

class RNNDecoder(nn.Module):
    def __init__(self, weight = None, attention=False, Freeze = True, hidden_size = 128, dropout =0, num_layers = 1):
        super(RNNDecoder, self).__init__()
        self.attention = attention
        if self.attention:
            self.Attn = nn.Linear(hidden_size, hidden_size, bias = True).to(device)
            self.Attn_Fc = nn.Linear(2 * hidden_size, hidden_size, bias = True).to(device)
        self.emb_layer = nn.Embedding(len(weight), len(weight[0]), padding_idx=PAD)
        self.emb_layer.weight.data.copy_(weight)
        if Freeze:
            self.emb_layer.weight.requires_grad = False
        self.lstm = nn.LSTM(input_size=len(weight[0]), hidden_size=hidden_size, num_layers=num_layers,
                           dropout=dropout).to(device)
        self.Fc = nn.Linear(hidden_size, len(weight)).to(device)

    def forward(self, output, lens, encoder_out, decoder_hidden):
        emb_layer = self.emb_layer(output.unsqueeze(0).to('cpu')).to(device)
        decoder_out, decoder_hidden = self.lstm(emb_layer, decoder_hidden)
        decoder_out = decoder_out.transpose(0,1)
        if not self.attention:
            output = self.Fc(decoder_out)
            return output.squeeze(1), decoder_hidden
        else:
            attn_logits = torch.bmm(decoder_out, self.Attn(encoder_out).transpose(0,1).transpose(1,2))
            attn_mask = masking(lens, attn_logits.size()[2]).unsqueeze(1)
            attn_logits.data.masked_fill_(attn_mask.data, -float('inf'))
            attn_weights = F.softmax(attn_logits.squeeze(1), dim=1).unsqueeze(1)
            attn_apply = torch.bmm(attn_weights, encoder_out.transpose(0,1))
            cat = torch.cat([attn_apply, decoder_out], -1)
            cat = F.tanh(self.Attn_Fc(cat))
            output = self.Fc(cat)
            return output.squeeze(1) , decoder_hidden, attn_weights.squeeze(1)

def masking(lens, MAX_len=None):
    max_len = lens.data.max()
    if MAX_len:
        max_len = MAX_len
    rang = torch.arange(0, max_len).long()
    rang = rang.unsqueeze(0).expand(lens.size(0), max_len)
    rang = Variable(rang).to(device)
    lens = (lens.unsqueeze(1).expand_as(rang))
    return rang > lens


def masked_cross_entropy(logits, target, length):
    logits_flat = logits.view(-1, logits.size(-1))
    log_probs_flat = F.log_softmax(logits_flat, dim = 1)
    target_flat = target.view(-1, 1)
    losses_flat = -torch.gather(log_probs_flat, dim=1, index=target_flat)
    losses = losses_flat.view(*target.size())
    mask = 1 - masking(length, target.size(1))
    losses = losses * mask.float()
    loss = losses.sum() / mask.float().sum()
    return loss


def train(input, output, in_lens, out_lens, encoder, decoder, encoder_optim, decoder_optim, criterion, max_grad_norm=1.618):
    input = input.to(device)
    output = output.to(device)
    in_lens = torch.LongTensor(in_lens).to(device)
    out_lens = torch.LongTensor(out_lens).to(device)
    batch_size = input.size(1)
    encodered = torch.LongTensor([SOS] * batch_size).to(device)
    decoder_outputs = torch.zeros(MAX_SENT_LENS + 1, batch_size, len(en_w2v)).to(device)
    encoder.train()
    decoder.train()
    encoder_optim.zero_grad()
    decoder_optim.zero_grad()
    encoder_outputs, decoder_hidden = encoder(input, in_lens.data.tolist(), hidden=None)
    use_teacher_forcing = True if random.random() < teacher_forcing_ratio else False
    if use_teacher_forcing:
        for t in range(MAX_SENT_LENS + 1):
            decoder_output, decoder_hidden = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
            decoder_outputs[t] = decoder_output
            encodered = output[t]
    else:
        eos_id = set()
        for t in range(MAX_SENT_LENS + 1):
            decoder_output, decoder_hidden = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
            try:
                decoder_output[ [ int(x) for x in eos_id]][PAD] = 1
                decoder_outputs[t] = decoder_output
            except:
                decoder_outputs[t] = decoder_output
            _, topi = F.log_softmax(decoder_output, dim = 1).topk(1)
            encodered = topi.squeeze().detach()
            indicator = encodered.eq(torch.LongTensor([EOS] * batch_size).to(device)).nonzero().squeeze().cpu().data.numpy().tolist()
            if indicator is not None:
                try:
                    for ind in indicator:
                        eos_id.add(ind)
                except:
                    eos_id.add(indicator)
    logits = decoder_outputs.transpose(0,1).transpose(1,2).contiguous()
    loss = criterion(logits, output.transpose(0,1).contiguous())
    loss.backward()
    encoder_clip_norm = nn.utils.clip_grad_norm(encoder.parameters(), max_grad_norm)
    decoder_clip_norm = nn.utils.clip_grad_norm(decoder.parameters(), max_grad_norm)
    encoder_optim.step()
    decoder_optim.step()
    return loss.item()


def train_attn(input, output, in_lens, out_lens, encoder, decoder, encoder_optim, decoder_optim, max_grad_norm=0.01):
    input = input.to(device)
    output = output.to(device)
    in_lens = torch.LongTensor(in_lens).to(device)
    out_lens = torch.LongTensor(out_lens).to(device)
    batch_size = input.size(1)
    encodered = torch.LongTensor([SOS] * batch_size).to(device)
    decoder_outputs = torch.zeros(MAX_SENT_LENS + 1, batch_size, len(en_w2v)).to(device)
    encoder.train()
    decoder.train()
    encoder_optim.zero_grad()
    decoder_optim.zero_grad()
    encoder_outputs, decoder_hidden = encoder(input, in_lens, hidden=None)
    use_teacher_forcing = True if random.random() < teacher_forcing_ratio else False
    if use_teacher_forcing:
        for t in range(MAX_SENT_LENS + 1):
            decoder_output, decoder_hidden, attention_weights = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
            decoder_outputs[t] = decoder_output
            encodered = output[t]
    else:
        for t in range(MAX_SENT_LENS + 1):
            decoder_output, decoder_hidden, attention_weights = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
            decoder_outputs[t] = decoder_output
            _, topi = F.log_softmax(decoder_output, dim = 1).topk(1)
            encodered = topi.squeeze().detach()
    logits = decoder_outputs.transpose(0,1).contiguous()
    loss = masked_cross_entropy(logits, output.transpose(0,1).contiguous(), out_lens)
    loss.backward()
    encoder_clip_norm = nn.utils.clip_grad_norm_(encoder.parameters(), max_grad_norm)
    decoder_clip_norm = nn.utils.clip_grad_norm_(decoder.parameters(), max_grad_norm)
    encoder_optim.step()
    decoder_optim.step()
    return loss.item()

BATCH_SIZE = 32
teacher_forcing_ratio = 1

train_iter = DataLoader(dataset=data,
                        batch_size=BATCH_SIZE,
                        shuffle=True,
                        collate_fn=collate_fn)

valid_iter = DataLoader(dataset=valid,
                        batch_size=BATCH_SIZE,
                        shuffle=True,
                        collate_fn=collate_fn_valid)


encoder = RNNEncoder(weight=zh_w2v, Freeze = False, hidden_size = 256, dropout =0.3, num_layers = 2)
decoder = RNNDecoder(weight=en_w2v, attention=True, Freeze = True, hidden_size = 512, dropout =0.3, num_layers = 2)

encoder_optim = optim.Adam([p for p in encoder.parameters() if p.requires_grad], lr=1e-3, weight_decay=1e-6)
decoder_optim = optim.Adam([q for q in decoder.parameters() if q.requires_grad], lr=1e-3, weight_decay=1e-6)

encoder_scheduler = torch.optim.lr_scheduler.LambdaLR(encoder_optim, lr_lambda=lambda epoch: 0.95 ** epoch)
decoder_scheduler = torch.optim.lr_scheduler.LambdaLR(decoder_optim, lr_lambda=lambda epoch: 0.95 ** epoch)

def greedy_evaluate(encoder, decoder, batch_data):
    input_g, in_lens_g, output_g, out_lens_g = batch_data
    batch_size = input_g.size(1)
    decoded_words = [[] for i in range(batch_size)]
    output_words = [[] for i in range(batch_size)]
    input_words = [[] for i in range(batch_size)]
    # for every sentence in the batch

    with torch.no_grad():
        encoder.eval()
        decoder.eval()


        input = input_g.to(device)
        output = output_g.to(device)
        in_lens = torch.LongTensor(in_lens_g).to(device)
        out_lens = torch.LongTensor(out_lens_g).to(device)

        encodered = torch.LongTensor([SOS] * batch_size).to(device)
        decoder_outputs = torch.zeros(MAX_SENT_LENS_VALID + 1, batch_size, len(en_w2v)).to(device)
        encoder_outputs, decoder_hidden = encoder(input, in_lens, hidden=None)
        eos_id = set()
        for t in range(MAX_SENT_LENS_VALID + 1):
            decoder_output, decoder_hidden, attention_weights = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
            decoder_outputs[t] = decoder_output
            _, topi = F.log_softmax(decoder_output, dim = 1).topk(1)
            encodered = topi.squeeze().detach()
            indicator = encodered.eq(torch.LongTensor([EOS] * batch_size).to(device)).nonzero().squeeze().cpu().data.numpy().tolist()
            if indicator is not None:
                try:
                    for ind in indicator:
                        eos_id.add(ind)
                except:
                    eos_id.add(indicator)
            for idx in range(batch_size):
                if idx in eos_id: continue
                decoded_words[idx].append(data.output_vocab['id2word'][int(encodered[idx])])
        output = output.transpose(0,1)
        input_g = input_g.transpose(0,1)
        for i in range(batch_size):
            output_words[i] =[data.output_vocab['id2word'][int(output[i][t])] for t in range(out_lens[i]-1)]
            output_corp.append(' '.join(output_words[i]))
            input_words[i] =[data.input_vocab['id2word'][int(input_g[i][t])] for t in range(in_lens[i]-1)]
            original_list.append(' '.join(input_words[i]))
            translated_corp.append(' '.join(decoded_words[i]))
    return

def Beam_Eval(encoder, decoder, batch_data, beam_size = 5):
    input_g, in_lens_g, output_g, out_lens_g = batch_data
    batch_size = input_g.size(1)
    translation_list = []
    decoded_words = [[] for i in range(batch_size)]
    output_words = [[] for i in range(batch_size)]
    with torch.no_grad():
        encoder.eval()
        decoder.eval()
        input = input_g.to(device)
        output = output_g.to(device)
        in_lens = torch.LongTensor(in_lens_g).to(device)
        out_lens = torch.LongTensor(out_lens_g).to(device)
        encodered = torch.LongTensor([SOS] * batch_size).to(device)
        encoder_outputs, decoder_hidden = encoder(input, in_lens, hidden = None)
        eos_id= set()
        for t in range(MAX_SENT_LENS_VALID + 1):
            decoder_output, decoder_hidden, __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
            topP, topI = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
            score_1 = torch.zeros(beam_size, beam_size , batch_size).to(device)
            score_2 = torch.zeros(beam_size, beam_size, beam_size , batch_size).to(device)
            for i, cand_I in enumerate(topI.transpose(0,1)):
                encodered = cand_I
                decoder_output, decoder_hidden_1 , __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
                tempP, tempI = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
                future_P = (topP.transpose(0,1)[i].repeat(beam_size,1) + tempP.transpose(0,1))
                score_1[i] = future_P.squeeze().detach()
                for j, cand_j in enumerate(tempI.transpose(0,1)):
                    encodered = cand_j
                    decoder_output, _ , __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden_1)
                    tempP2, tempI2 = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
                    score_2[i][j] = topP.transpose(0,1)[i].repeat(beam_size,1) + tempP.transpose(0,1)[j].repeat(beam_size,1) + tempP2.transpose(0,1).squeeze().detach()
            ids = torch.argmax(score_2.view(beam_size*beam_size*beam_size, batch_size), dim = 0)
            for idx in range(batch_size):
                encodered[idx] = topI[idx][(ids[idx]//beam_size)//beam_size]
            indicator = encodered.eq(torch.LongTensor([EOS] * batch_size).to(device)).nonzero().squeeze().cpu().data.numpy().tolist()
            if indicator is not None:
                try:
                    for ind in indicator:
                        eos_id.add(ind)
                except:
                    eos_id.add(indicator)
            for idx in range(batch_size):
                if idx in eos_id: continue
                decoded_words[idx].append(data.output_vocab['id2word'][int(encodered[idx])])
        output = output.transpose(0,1)
        for i in range(batch_size):
            output_words[i] =[data.output_vocab['id2word'][int(output[i][t])] for t in range(out_lens[i]-1)]
            output_corp.append(' '.join(output_words[i]))
            translated_corp.append(' '.join(decoded_words[i]))
    return


import pickle
Bleu_score = []
train_loss = []
for epoch in range(30):
    total_loss = 0
    for idx, batch_data in enumerate(train_iter):
        input, in_lens, output, out_lens = batch_data
        loss = train_attn(input, output, in_lens, out_lens, encoder, decoder, encoder_optim, decoder_optim, 0.1)
        total_loss += loss
        if idx%800 == 0:
            print('Training Loss: {}'.format(loss))
    train_loss.append((total_loss/(idx+ 1)))
    translated_corp = []
    output_corp = []
    for idx, batch_data in enumerate(valid_iter):
            input, in_lens, output, out_lens = batch_data
            Beam_evaluate(encoder, decoder, batch_data)

    BLEU_score_epo = sacrebleu.raw_corpus_bleu(translated_corp, [output_corp]).score
    print('Validation Score After Epoch: {}'.format(BLEU_score_epo))
    try:
        if BLEU_score_epo > max(Bleu_score):
            torch.save(encoder.state_dict(), 'encoder_vi.pth')
            torch.save(decoder.state_dict(), 'decoder_vi.pth')
    except:
        torch.save(encoder.state_dict(), 'encoder_vi.pth')
        torch.save(decoder.state_dict(), 'decoder_vi.pth')
    Bleu_score.append(BLEU_score_epo)
    print(train_loss)
    print(Bleu_score)
