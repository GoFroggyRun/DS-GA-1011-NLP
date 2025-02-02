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

class MultiHeadAttention(nn.Module):
    def __init__(self, n_head, d_qin, d_kin, d_model, dropout=0.1):
        super().__init__()
        assert d_model % n_head == 0
        self.n_head = n_head
        self.d_k = d_model//n_head
        self.w_qs = nn.Linear(d_qin, d_model)
        self.w_ks = nn.Linear(d_kin, d_model)
        self.w_vs = nn.Linear(d_kin, d_model)
        nn.init.normal_(self.w_qs.weight, mean=0, std=np.sqrt(2.0 / (d_model + self.d_k)))
        nn.init.normal_(self.w_ks.weight, mean=0, std=np.sqrt(2.0 / (d_model + self.d_k)))
        nn.init.normal_(self.w_vs.weight, mean=0, std=np.sqrt(2.0 / (d_model + self.d_k)))
        self.attention = DotAttention(norm= self.d_k ** 0.5)
        self.layer_norm = nn.LayerNorm(d_model)
        self.fc = nn.Linear(d_model, d_model)
        nn.init.xavier_normal_(self.fc.weight)
        self.dropout = nn.Dropout(dropout)

    def forward(self, q, k, v, mask=None):
        d_k, n_head = self.d_k, self.n_head
        len_q, sz_b= q.size()[:2]
        len_k = k.size(0)
        residual = q
        mask = mask.repeat(n_head, 1, 1)  #[batch x n head, seq len, seq len]
        q = q.transpose(0,1).view(sz_b, len_q, n_head, d_k).transpose(1,2).contiguous().view(sz_b*n_head, len_q, d_k) # [batch, n head, seq len, dk]
        k = k.transpose(0,1).view(sz_b, len_k, n_head, d_k).transpose(1,2).contiguous().view(sz_b*n_head, len_k, d_k)
        v = v.transpose(0,1).view(sz_b, len_k, n_head, d_k).transpose(1,2).contiguous().view(sz_b*n_head, len_k, d_k)
        output, attn = self.attention(q, k, v, mask=mask)
        output = output.view(n_head, sz_b, len_q, d_k)
        output = output.permute(1, 2, 0, 3).contiguous().view(sz_b, len_q, -1)
        output = self.dropout(self.fc(output))
        output = output.transpose(0,1)
        output = self.layer_norm(output + residual)
        return output, attn

class CNNFeed(nn.Module):
    def __init__(self, d_in, d_hid, dropout=0.1):
        super().__init__()
        self.w_1 = nn.Conv1d(d_in, d_hid, 1)
        self.w_2 = nn.Conv1d(d_hid, d_in, 1)
        self.layer_norm = nn.LayerNorm(d_in)
        self.dropout = nn.Dropout(dropout)
    def forward(self, x):
        residual = x
        output = x.transpose(1, 2)
        output = self.w_2(F.relu(self.w_1(output)))
        output = output.transpose(1, 2)
        output = self.dropout(output)
        output = self.layer_norm(output+ residual)

        return output

class DotAttention(nn.Module):
    def __init__(self, norm, attn_dropout=0.1):
        super().__init__()
        self.norm = norm
        self.dropout = nn.Dropout(attn_dropout)
        self.softmax = nn.Softmax(dim=2)
    def forward(self, q, k, v, mask=None):
        attn = torch.bmm(q, k.transpose(1, 2))
        attn = attn / self.norm
        if mask is not None:
            attn = attn.masked_fill(mask, -1e9)
        attn = self.softmax(attn)
        attn = self.dropout(attn)
        output = torch.bmm(attn, v)

        return output, attn


class EncoderLayer(nn.Module):
    def __init__(self, d_qin, d_kin, d_model, n_head, dropout=0.1):
        super(EncoderLayer, self).__init__()
        self.slf_attn = MultiHeadAttention(
            n_head, d_qin, d_kin, d_model, dropout=dropout)
        self.pos_ffn = CNNFeed(d_model, d_model, dropout=dropout)

    def forward(self, enc_input, non_pad_mask=None, slf_attn_mask=None):
        enc_output, attn = self.slf_attn(
            enc_input, enc_input, enc_input, mask=slf_attn_mask)
        enc_output *= non_pad_mask
        enc_output = self.pos_ffn(enc_output)
        enc_output *= non_pad_mask
        return enc_output, attn

class DecoderLayer(nn.Module):
    def __init__(self, d_q, d_k, d_model, d_inner, n_head, dropout=0.1):
        super(DecoderLayer, self).__init__()
        self.slf_attn = MultiHeadAttention(
            n_head, d_q, d_q, d_model, dropout=dropout)
        self.slf_src_attn = MultiHeadAttention(
            n_head, d_q, d_k, d_model, dropout=dropout)
        self.pos_ffn = CNNFeed(d_model, d_inner, dropout=dropout)
    def forward(self, dec_input, enc_output, non_pad_mask=None, slf_src_attn_mask=None, slf_tgt_attn_mask=None):
        dec_output, attn_dec = self.slf_attn(dec_input, dec_input, dec_input, mask=slf_tgt_attn_mask)
        dec_output *= non_pad_mask
        dec_output, attn_enc = self.slf_src_attn(dec_input, enc_output, enc_output, mask=slf_src_attn_mask)
        dec_output *= non_pad_mask
        dec_output = self.pos_ffn(dec_output)
        dec_output *= non_pad_mask
        return dec_output, attn_dec, attn_enc


class Decoder(nn.Module):
    def __init__(self, weight, n_layers, n_head, d_model, d_inner, dropout=0.1):
        super().__init__()
        self.n_layers = n_layers
        n_position = max(MAX_SENT_LENS,MAX_SENT_LENS_VALID) + 3
        self.emb_layer = nn.Embedding(len(weight), len(weight[0]), padding_idx=PAD)
        self.emb_layer.weight.data.copy_(weight)
        self.position_enc = nn.Embedding.from_pretrained(
            get_sinusoid_encoding_table(n_position, len(weight[0]), padding_idx=PAD),
            freeze=True)
        self.layer_stack = nn.ModuleList([DecoderLayer(len(weight[0]), d_model, d_model, d_inner, n_head, dropout=dropout)])
        for i in range(n_layers-1):
            self.layer_stack.append(DecoderLayer(d_model, d_model, d_model, d_inner, n_head, dropout=dropout))
        self.Fc = nn.Linear(d_model, len(weight), bias=False).to(device)


    def forward(self, tgt_seq, encoder_output, src_seq, tgt_len):
        emb_layer = self.emb_layer(tgt_seq).to(device)
        slf_src_attn_mask = get_pad_mask(src_seq, tgt_seq)
        slf_tgt_attn_mask = get_pad_mask(tgt_seq, tgt_seq)
        subseq_mask = get_sub_mask(tgt_seq)
        slf_attn_mask = (slf_tgt_attn_mask + subseq_mask).gt(0)
        non_pad_mask = get_non_pad_mask(tgt_seq)
        batch_pos = np.array([
        [pos_i+1 if w_i != PAD else 0
         for pos_i, w_i in enumerate(inst)] for inst in tgt_seq.transpose(0,1)])
        batch_pos = torch.LongTensor(batch_pos).transpose(0,1)
        dec_output = self.emb_layer(tgt_seq) + self.position_enc(batch_pos.to(device))
        for dec_layer in self.layer_stack:
            dec_output, attn_dec, attn_enc = dec_layer(
                dec_output, encoder_output,
                non_pad_mask=non_pad_mask,
                slf_src_attn_mask=slf_src_attn_mask,
                slf_tgt_attn_mask=slf_attn_mask)
            try:
                enc_slf_attn = torch.cat([enc_slf_attn, attn_enc.transpose(0,1)], dim = 2)
                dec_slf_attn = torch.cat([dec_slf_attn, attn_dec.transpose(0,1)], dim = 2)
            except:
                enc_slf_attn = attn_enc.transpose(0,1)
                dec_slf_attn = attn_dec.transpose(0,1)
        dec_output = self.Fc(dec_output)
        return dec_output


def get_non_pad_mask(seq):
    assert seq.dim() == 2
    return seq.ne(PAD).type(torch.float).unsqueeze(-1)

def get_sinusoid_encoding_table(n_position, d_hid, padding_idx=PAD):
    def _cal_angle(position, hid_idx):
        return position / np.power(10000, 2 * (hid_idx // 2) / d_hid)
    def _get_posi_angle_vec(position):
        return [_cal_angle(position, hid_j) for hid_j in range(d_hid)]
    sinusoid_table = np.array([_get_posi_angle_vec(pos_i) for pos_i in range(n_position)])
    sinusoid_table[:, 0::2] = np.sin(sinusoid_table[:, 0::2])
    sinusoid_table[:, 1::2] = np.cos(sinusoid_table[:, 1::2])
    sinusoid_table[padding_idx] = 0.
    return torch.FloatTensor(sinusoid_table)

def get_pad_mask(seq, seq2):
    #change
    padding_mask = seq.eq(PAD)
    padding_mask = padding_mask.transpose(0,1)
    len = seq2.size(0)
    padding_mask = padding_mask.unsqueeze(1).expand(-1, len, -1)

    return padding_mask

def get_sub_mask(seq):
    len_s, sz_b = seq.size()
    subsequent_mask = torch.triu(
        torch.ones((len_s, len_s), device=seq.device, dtype=torch.uint8), diagonal=1)
    subsequent_mask = subsequent_mask.unsqueeze(0).expand(sz_b, -1, -1)  # b x ls x ls

    return subsequent_mask

class Encoder(nn.Module):
    def __init__(self, weight,
            n_layers, n_head, d_in, d_model, RNN_Dec = False, dropout=0.1):

        super().__init__()
        self.n_layers = n_layers
        self.RNN_Dec = RNN_Dec
        n_position = max(MAX_SENT_LENS,MAX_SENT_LENS_VALID) + 3

        self.emb_layer = nn.Embedding(len(weight), len(weight[0]), padding_idx=PAD)
        self.emb_layer.weight.data.copy_(weight)

        self.position_enc = nn.Embedding.from_pretrained(
            get_sinusoid_encoding_table(n_position, len(weight[0]), padding_idx=PAD),
            freeze=True)
        if self.RNN_Dec:
            self.layer_stack = nn.ModuleList([EncoderLayer(d_in, d_in, d_model, n_head, dropout=dropout)])
            for i in range(n_layers - 1):
                self.layer_stack.append(EncoderLayer(d_model, d_model, d_model, n_head, dropout=dropout))
            self.Fc1 = nn.Linear(self.n_layers *(MAX_SENT_LENS + 1)*(MAX_SENT_LENS + 1), (MAX_SENT_LENS + 1)*(MAX_SENT_LENS + 1), bias =False)
            self.Fc2 = nn.Linear((MAX_SENT_LENS + 1)*(MAX_SENT_LENS + 1), d_model, bias =False)
        else:
            self.layer_stack = nn.ModuleList([EncoderLayer(d_in, d_in, d_model, n_head, dropout=dropout)])
            for i in range(n_layers - 1):
                self.layer_stack.append(EncoderLayer(d_model, d_model, d_model, n_head, dropout=dropout))


    def forward(self, src_seq, src_len):
        emb_layer = self.emb_layer(src_seq).to(device)
        slf_attn_mask = get_pad_mask(src_seq, src_seq)
        non_pad_mask = get_non_pad_mask(src_seq)
        batch_pos = np.array([
        [pos_i+1 if w_i != PAD else 0
         for pos_i, w_i in enumerate(inst)] for inst in src_seq.transpose(0,1)])
        batch_pos = torch.LongTensor(batch_pos).transpose(0,1)
        enc_output = self.emb_layer(src_seq) + self.position_enc(batch_pos.to(device))
        for enc_layer in self.layer_stack:
            enc_output, attn = enc_layer(
                enc_output,
                non_pad_mask=non_pad_mask,
                slf_attn_mask=slf_attn_mask)
            try:
                enc_slf_attn = torch.cat([enc_slf_attn, attn.transpose(0,1)], dim = 2)
            except:
                enc_slf_attn = attn.transpose(0,1)
        if self.RNN_Dec:
            seq_lens = enc_output.size()[0]
            batch_size = src_seq.size(1)
            hn = enc_slf_attn.transpose(0,1).view(batch_size, -1, self.n_layers * seq_lens*seq_lens)
            hn = self.Fc1(hn.to(device))
            hn = F.relu(hn)
            hn = self.Fc2(hn.to(device)).transpose(1,0)
            cn = F.tanh(hn)
            decoder_hidden = (hn, cn)
            decoder_hidden = tuple([torch.cat([sum(h[0:h.size(0):2]).unsqueeze(0) , sum(h[1:h.size(0):2]).unsqueeze(0)], dim=0) for h in decoder_hidden])
            return enc_output, decoder_hidden
        else:
            return enc_output


def train_full_self(input, output, in_lens, out_lens, encoder, decoder, encoder_optim, decoder_optim, max_grad_norm=0.01):
    encoder.train()
    decoder.train()
    input = input.to(device)
    output = output.to(device)
    in_lens = torch.LongTensor(in_lens).to(device)
    out_lens = torch.LongTensor(out_lens).to(device)
    batch_size = input.size(1)
    encodered = torch.LongTensor([SOS] * batch_size).to(device)
    decoder_outputs = torch.zeros(MAX_SENT_LENS + 1, batch_size, len(en_w2v)).to(device)
    encoder_optim.zero_grad()
    decoder_optim.zero_grad()
    encoder_outputs = encoder(input, in_lens)
    decoder_output = decoder(output[:-1], encoder_outputs, input, out_lens[:-1])

    logits = decoder_output.transpose(0,1).transpose(1,2).contiguous()
    loss = criterion(logits, output[1:].transpose(0,1).contiguous())
    loss.backward()
    encoder_clip_norm = nn.utils.clip_grad_norm_(encoder.parameters(), max_grad_norm)
    decoder_clip_norm = nn.utils.clip_grad_norm_(decoder.parameters(), max_grad_norm)
    encoder_optim.step()
    decoder_optim.step()

    return loss.item()


BATCH_SIZE = 32
teacher_forcing_ratio = 1
criterion = nn.CrossEntropyLoss(ignore_index=0)
train_iter = DataLoader(dataset=data,
                        batch_size=BATCH_SIZE,
                        shuffle=True,
                        collate_fn=collate_fn)

valid_iter = DataLoader(dataset=valid,
                        batch_size=BATCH_SIZE,
                        shuffle=True,
                        collate_fn=collate_fn_valid)

encoder = Encoder(weight=zh_w2v, n_layers=4, n_head=4, d_in=300, d_model=300, RNN_Dec = False, dropout=0.1).to(device)
decoder = Decoder(weight=en_w2v, n_layers=4, n_head=4, d_model=300, d_inner=1048, dropout=0.1).to(device)

encoder_optim = optim.Adam([p for p in encoder.parameters() if p.requires_grad], lr=3e-4, betas=(0.9, 0.98), eps=1e-9, weight_decay=1e-6)
decoder_optim = optim.Adam([q for q in decoder.parameters() if q.requires_grad], lr=3e-4 , betas=(0.9, 0.98), eps=1e-9, weight_decay=1e-6)


encoder_scheduler = torch.optim.lr_scheduler.LambdaLR(encoder_optim, lr_lambda=lambda epoch: 0.95 ** epoch)
decoder_scheduler = torch.optim.lr_scheduler.LambdaLR(decoder_optim, lr_lambda=lambda epoch: 0.95 ** epoch)


def greedy_evaluate(encoder, decoder, batch_data):
    input_g, in_lens_g, output_g, out_lens_g = batch_data
    batch_size = input_g.size(1)
    translation_list = []
    decoded_words = [[] for i in range(batch_size)]
    output_words = [[] for i in range(batch_size)]
    # for every sentence in the batch

    with torch.no_grad():
        encoder.eval()
        decoder.eval()


        input = input_g.to(device)
        output = output_g.to(device)
        in_lens = torch.LongTensor(in_lens_g).to(device)
        out_lens = torch.LongTensor(out_lens_g).to(device)
        decoder_in = torch.zeros(MAX_SENT_LENS_VALID + 3, batch_size).to(device)
        encodered = torch.LongTensor([SOS] * batch_size).to(device)
        decoder_outputs = torch.zeros(MAX_SENT_LENS_VALID + 1, batch_size, len(en_w2v)).to(device)
        encoder_outputs = encoder(input, in_lens)
        #print(encoder_outputs[0])
        #print(encoder_outputs[1])
        eos_id = set()
        for t in range(MAX_SENT_LENS_VALID + 1):
            tgt_len = [t+1]*batch_size
            decoder_in[t] = encodered
            decoder_in = decoder_in.to(torch.long)
            decoder_output = decoder(decoder_in[:(t+1)], encoder_outputs, input, tgt_len)


            _, topi = F.log_softmax(decoder_output[-1], dim = 1).topk(1)
            encodered = topi.squeeze().detach()
            #print(encodered.size())
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
            output_corp_g.append(' '.join(output_words[i]))
            translated_corp_g.append(' '.join(decoded_words[i]))

def Beam_Eval_long_time(encoder, decoder, batch_data, beam_size = 5):
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
        encoder_outputs, decoder_hidden = encoder(input, in_lens)
        eos_id= set()
        for t in range(MAX_SENT_LENS_VALID + 1):
            decoder_output, decoder_hidden, __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
            topP, topI = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
            score_5 = torch.zeros(beam_size, beam_size, beam_size, beam_size, beam_size, beam_size , batch_size).to(device)
            for i, cand_I in enumerate(topI.transpose(0,1)):
                encodered = cand_I
                decoder_output, decoder_hidden_1 , __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden)
                tempP, tempI = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
                for j, cand_j in enumerate(tempI.transpose(0,1)):
                    encodered = cand_j
                    decoder_output, decoder_hidden_2 , __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden_1)
                    tempP2, tempI2 = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
                    for k, cand_k in enumerate(tempI2.transpose(0,1)):
                        encodered = cand_k
                        decoder_output, decoder_hidden_3, __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden_2)
                        tempP3, tempI3 = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
                        for p, cand_p in enumerate(tempI3.transpose(0,1)):
                            encodered = cand_p
                            decoder_output, decoder_hidden_4, __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden_3)
                            tempP4, tempI4 = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
                            for q, cand_q in enumerate(tempI4.transpose(0,1)):
                                encodered = cand_q
                                decoder_output, _, __ = decoder(encodered, in_lens, encoder_outputs, decoder_hidden_4)
                                tempP5, tempI5 = F.log_softmax(decoder_output, dim = 1).topk(beam_size)
                                score_5[i][j][k][p][q] = topP.transpose(0,1)[i].repeat(beam_size,1) + tempP.transpose(0,1)[j].repeat(beam_size,1) + tempP2.transpose(0,1)[k].repeat(beam_size,1) + tempP3.transpose(0,1)[p].repeat(beam_size,1) + tempP4.transpose(0,1)[q].repeat(beam_size,1) + tempP5.transpose(0,1).squeeze().detach()
            ids = torch.argmax(score_5.view(beam_size*beam_size*beam_size*beam_size*beam_size*beam_size, batch_size), dim = 0)
            for idx in range(batch_size):
                encodered[idx] = topI[idx][((((ids[idx]//beam_size)//beam_size)//beam_size)//beam_size)//beam_size]
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


def Beam_Eval(encoder, decoder, batch_data, beam_size = 5):
    input_g, in_lens_g, output_g, out_lens_g = batch_data
    batch_size = input_g.size(1)
    translation_list = []
    decoded_words = [[] for i in range(batch_size)]
    output_words = [[] for i in range(batch_size)]
    # for every sentence in the batch

    with torch.no_grad():
        encoder.eval()
        decoder.eval()


        input = input_g.to(device)
        output = output_g.to(device)
        in_lens = torch.LongTensor(in_lens_g).to(device)
        out_lens = torch.LongTensor(out_lens_g).to(device)
        encodered = torch.LongTensor([SOS] * batch_size).to(device)
        decoder_in = torch.zeros(MAX_SENT_LENS_VALID + 3, batch_size).to(device)
        encoder_outputs = encoder(input, in_lens)
        outputs = torch.zeros(MAX_SENT_LENS_VALID + 1, batch_size, len(en_w2v)).to(device)
        #print(encoder_outputs.size())
        print(encoder_outputs[0])
        print(encoder_outputs[1])
        eos_id= set()
        for t in range(MAX_SENT_LENS_VALID + 1):
            tgt_len = [t+1]*batch_size
            decoder_in[t] = encodered
            decoder_in = decoder_in.to(torch.long)
            decoder_output = decoder(decoder_in[:(t+1)], encoder_outputs, input, tgt_len)
            outputs[t] = decoder_output[-1]
            #_, next_word = torch.max(outputs[t], dim=1)
            #try: encodered = torch.cat([encodered, next_word.unsqueeze(0)], dim=0)
            #except: encodered = torch.cat([encodered.unsqueeze(0), next_word.unsqueeze(0)], dim=0)
            topP, topI = F.log_softmax(decoder_output[-1], dim = 1).topk(beam_size)
            score_tmp = torch.zeros( beam_size, beam_size , batch_size).to(device)
            for i, cand_I in enumerate(topI.transpose(0,1)):
                tgt_len = [t+2]*batch_size
                encodered = cand_I
                decoder_in[t+1] = encodered
                decoder_output = decoder(decoder_in[:(t+2)], encoder_outputs, input, tgt_len)
                tempP, tempI = F.log_softmax(decoder_output[-1], dim = 1).topk(beam_size)
                future_P = (topP.transpose(0,1)[i].repeat(beam_size,1) + tempP.transpose(0,1))
                score_tmp[i] = future_P.squeeze().detach()
            ids = torch.argmax(score_tmp.view(beam_size*beam_size, batch_size), dim = 0)
            for idx in range(batch_size):
                encodered[idx] = topI[idx][ids[idx]//beam_size]
            indicator = encodered.eq(torch.LongTensor([EOS] * batch_size).to(device)).nonzero().squeeze().cpu().data.numpy().tolist()
            #print(encodered)
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


def loss_evaluate(encoder, decoder, batch_data):
    input_g, in_lens_g, output_g, out_lens_g = batch_data
    batch_size = input_g.size(1)
    translation_list = []
    decoded_words = [[] for i in range(batch_size)]
    output_words = [[] for i in range(batch_size)]
    # for every sentence in the batch

    with torch.no_grad():
        encoder.eval()
        decoder.eval()


        input = input_g.to(device)
        output = output_g.to(device)
        in_lens = torch.LongTensor(in_lens_g).to(device)
        out_lens = torch.LongTensor(out_lens_g).to(device)
        decoder_in = torch.zeros(MAX_SENT_LENS_VALID + 3, batch_size).to(device)
        encodered = torch.LongTensor([SOS] * batch_size).to(device)
        decoder_outputs = torch.zeros(MAX_SENT_LENS_VALID + 1, batch_size, len(en_w2v)).to(device)
        encoder_outputs = encoder(input, in_lens)
        #print(encoder_outputs[0])
        #print(encoder_outputs[1])
        #decoder_outputs[0] = encodered

        eos_id = set()
        for t in range(MAX_SENT_LENS_VALID +1):
            tgt_len = [t+1]*batch_size
            decoder_in[t] = encodered
            decoder_in = decoder_in.to(torch.long)
            decoder_output = decoder(decoder_in[:(t+1)], encoder_outputs, input, tgt_len)
            _, topi = F.log_softmax(decoder_output[-1], dim = 1).topk(1)
            encodered = topi.squeeze().detach()
            #print(encodered.size())
            decoder_outputs[t] = decoder_output[-1]

        #decoder_outputs = decoder(output[:-1], encoder_outputs, input, out_lens[:-1])

        logits = decoder_outputs.transpose(0,1).transpose(1,2).contiguous()
        loss = criterion(logits, output[1:].transpose(0,1).contiguous())

    return loss.item()


import pickle
beam_score = []
greedy_score = []
#Bleu_score_beam = []
train_loss = []
val_losses = []
teacher_forcing_ratio =1
for epoch in range(25):
    encoder_scheduler.step()
    decoder_scheduler.step()
    total_loss = 0
    for idx, batch_data in enumerate(train_iter):
        input, in_lens, output, out_lens = batch_data
        loss = train_full_self(input, output, in_lens, out_lens, encoder, decoder, encoder_optim, decoder_optim,
                         max_grad_norm = 10)
        total_loss += loss
        if idx%800 == 0:
            print('Training Loss: {}'.format(loss))
    train_loss.append((total_loss/(idx+ 1)))
    translated_corp = []
    output_corp = []
    translated_corp_g = []
    output_corp_g = []
    total_val_loss = 0
    for idx, batch_data in enumerate(valid_iter):
            input, in_lens, output, out_lens = batch_data
            #Beam_Eval(encoder, decoder, batch_data)
            greedy_evaluate(encoder, decoder, batch_data)
            val_loss = loss_evaluate(encoder, decoder, batch_data)
            total_val_loss += val_loss
    val_losses.append((total_val_loss/(idx+ 1)))
    #beam_score_epo = sacrebleu.corpus_bleu(translated_corp, [output_corp]).score
    #print('Validation beam Score After Epoch: {}'.format(beam_score_epo))
    #greedy_score_epo = sacrebleu.corpus_bleu(translated_corp_g, [output_corp_g]).score
    #print('Validation greedy Score After Epoch: {}'.format(greedy_score_epo))
    try:
        if BLEU_score_epo > max(Bleu_score):
            torch.save(encoder.state_dict(), 'encoder_vi_fullself.pth')
            torch.save(decoder.state_dict(), 'decoder_vi_fullself.pth')
    except:
        torch.save(encoder.state_dict(), 'encoder_vi_fullself.pth')
        torch.save(decoder.state_dict(), 'decoder_vi_fullself.pth')
    #beam_score.append(beam_score_epo)
    #greedy_score.append(greedy_score_epo)
    with open('log_vi_fullself.txt', 'w') as f:
        for loss, val in zip(train_loss,val_losses):
            f.write("%s, %s \n" %(loss, val))
    print(train_loss)
    print(val_losses)
    #print(beam_score)
    #print(greedy_score)
