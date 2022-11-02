# -*- coding: utf-8 -*-
"""medical_re.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1nddzA4hsk1pr9u1HobaxbAJr2M1QAr-K
"""

import random
import json
import numpy as np
import torch
import torch.nn as nn
# from constant import ProductionConfig as Path
from transformers import BertTokenizer, BertModel, AdamW
from itertools import cycle
import gc
import random
import time
import re

class config:
    batch_size = 1  # 测试小一点
    max_seq_len = 256
    num_p = 23  # 关系类别数，分类任务，自己定义好
    learning_rate = 1e-5
    EPOCH = 2

    """
    几个概念：
        spo：主体-关系-客体
    """

    PATH_SCHEMA = "/Users/apple/fileImp/CV/CMeKG/CMeKG_tools/predicate.json"
    PATH_TRAIN = '/Users/apple/fileImp/CV/CMeKG/CMeKG_tools/train_example.json'
    PATH_BERT = "/Users/apple/fileImp/CV/CMeKG/CMeKG_tools/medical_re/"
    PATH_MODEL = "/Users/apple/fileImp/CV/CMeKG/CMeKG_tools/medical_re/model_re.pkl"
    PATH_SAVE = '/Users/apple/fileImp/CV/CMeKG/CMeKG_tools/save/model_re.pkl'
    tokenizer = BertTokenizer.from_pretrained("/Users/apple/fileImp/CV/CMeKG/CMeKG_tools/medical_re/vocab.txt")

    id2predicate = {}
    predicate2id = {}



class IterableDataset(torch.utils.data.IterableDataset):
    def __init__(self, data, random):
        super(IterableDataset).__init__()
        self.data = data
        self.random = random
        self.tokenizer = config.tokenizer

    def __len__(self):
        return len(self.data)

    def search(self, sequence, pattern):
        n = len(pattern)
        for i in range(len(sequence)):
            if sequence[i:i + n] == pattern:
                return i
        return -1

    def process_data(self):
        idxs = list(range(len(self.data)))
        if self.random:
            np.random.shuffle(idxs)
        batch_size = config.batch_size
        max_seq_len = config.max_seq_len
        num_p = config.num_p

        """
        数据预处理
        
        一系列指标：
            batch_token_ids: [1, 256] 
                input id 输入字符编码
            batch_mask_ids: [1, 256]
                mask id 每个字符是否参与transformer 是否参与计算
            batch_segment_ids: [1, 256]
                segment：段
                指定输入中每个字符分别是第几句话（段）
            batch_subject_ids: [1, 2]
                subject: 主体
                一个主体的起始和结束位置，一个主体一个主体的训练，不是所有主体一起训练
                以主体为单位去训练
            batch_subject_labels: [1, 256, 2]
                subject: 主体
                主体标签，每个字符是主体的起始和结束位置标签
            batch_object_labels: [1, 256, 23, 2]
                object: 客体
                客体标签，每个字符是否与已确定的主体有关系，如果有关系确定是什么关系，
                并且确定客体的起始和终止位置标签
        """
        batch_token_ids = np.zeros((batch_size, max_seq_len), dtype=np.int)
        batch_mask_ids = np.zeros((batch_size, max_seq_len), dtype=np.int)
        batch_segment_ids = np.zeros((batch_size, max_seq_len), dtype=np.int)
        batch_subject_ids = np.zeros((batch_size, 2), dtype=np.int)
        batch_subject_labels = np.zeros((batch_size, max_seq_len, 2), dtype=np.int)
        batch_object_labels = np.zeros((batch_size, max_seq_len, num_p, 2), dtype=np.int)
        batch_i = 0
        for i in idxs:
            text = self.data[i]['text']
            """
            encode完的结果是什么？好像是对应字符表中的字符id，
            还没有编码embedding，编码是在bert模型中做的
            """
            batch_token_ids[batch_i, :] = self.tokenizer.encode(text, max_length=max_seq_len, pad_to_max_length=True,
                                                                add_special_tokens=True)
            batch_mask_ids[batch_i, :len(text) + 2] = 1
            spo_list = self.data[i]['spo_list']
            """
            这个随机选择的idx 观测数据默认是一个spo list 里都是同一个主体
            如果一个spo list里有多个不同的主体 这个逻辑就需要改进
            """
            idx = np.random.randint(0, len(spo_list), size=1)[0]  # 有多个主体，每次随机选择一个主体
            s_rand = self.tokenizer.encode(spo_list[idx][0])[1:-1]  # 主体ID编码 [1:-1] 去掉特殊符号
            s_rand_idx = self.search(list(batch_token_ids[batch_i, :]), s_rand)
            batch_subject_ids[batch_i, :] = [s_rand_idx, s_rand_idx + len(s_rand) - 1]
            for i in range(len(spo_list)):
                spo = spo_list[i]
                s = self.tokenizer.encode(spo[0])[1:-1]
                p = config.prediction2id[spo[1]]
                o = self.tokenizer.encode(spo[2])[1:-1]
                s_idx = self.search(list(batch_token_ids[batch_i]), s)
                o_idx = self.search(list(batch_token_ids[batch_i]), o)
                if s_idx != -1 and o_idx != -1:
                    batch_subject_labels[batch_i, s_idx, 0] = 1  # 起始位置
                    batch_subject_labels[batch_i, s_idx + len(s) - 1, 1] = 1  # 终止位置
                    if s_idx == s_rand_idx:  # 遍历的主体是否为上面随机选的主体
                        batch_object_labels[batch_i, o_idx, p, 0] = 1  # 起始位置
                        batch_object_labels[batch_i, o_idx + len(o) - 1, p, 1] = 1  # 终止位置
            batch_i += 1
            if batch_i == batch_size or i == idxs[-1]:
                yield batch_token_ids, batch_mask_ids, batch_segment_ids, batch_subject_labels, batch_subject_ids, batch_object_labels
                batch_token_ids[:, :] = 0
                batch_mask_ids[:, :] = 0
                batch_subject_ids[:, :] = 0
                batch_subject_labels[:, :, :] = 0
                batch_object_labels[:, :, :, :] = 0
                batch_i = 0

    """
    这个 dataloader 写的不是很标准，可以参考下pytorch的标准dataloader写法
    """

    def get_stream(self):
        return cycle(self.process_data())  # cycle 重复循环的取数据集中的每一个数据

    def __iter__(self):
        return self.get_stream()

# 就是
class Model4s(nn.Module):
    def __init__(self, hidden_size=768):
        super(Model4s, self).__init__()
        self.bert = BertModel.from_pretrained(config.PATH_BERT)
        for param in self.bert.parameters():
            param.requires_grad = True
        self.dropout = nn.Dropout(p=0.2)
        """ 
        out_features=2 预测一个句子中每个位置是否是主体的开始和结束位置，
        S & E，这是基于每个字去做的
        这个2还是没弄清楚
        """
        self.linear = nn.Linear(in_features=hidden_size, out_features=2, bias=True)
        self.sigmoid = nn.Sigmoid()

    def forward(self, input_ids, input_mask, segment_ids, hidden_size=768):
        hidden_states = self.bert(input_ids,
                                  attention_mask=input_mask,
                                  token_type_ids=segment_ids)[0]  # (batch_size, sequence_length, hidden_size)
        output = self.sigmoid(self.linear(self.dropout(hidden_states))).pow(2)

        return output, hidden_states


class Model4po(nn.Module):
    def __init__(self, num_p=config.num_p, hidden_size=768):
        super(Model4po, self).__init__()
        self.dropout = nn.Dropout(p=0.4)
        self.linear = nn.Linear(in_features=hidden_size, out_features=num_p * 2, bias=True)
        self.sigmoid = nn.Sigmoid()

    def forward(self, hidden_states, batch_subject_ids, input_mask):
        all_s = torch.zeros((hidden_states.shape[0], hidden_states.shape[1], hidden_states.shape[2]),
                            dtype=torch.float32)

        for b in range(hidden_states.shape[0]):
            s_start = batch_subject_ids[b][0]
            s_end = batch_subject_ids[b][1]
            s = hidden_states[b][s_start] + hidden_states[b][s_end]
            cue_len = torch.sum(input_mask[b])
            all_s[b, :cue_len, :] = s
        hidden_states += all_s

        output = self.sigmoid(self.linear(self.dropout(hidden_states))).pow(4)

        return output  # (batch_size, max_seq_len, num_p*2)


def load_schema(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        data = json.load(f)
        predicate = list(data.keys())
        prediction2id = {}
        id2predicate = {}
        for i in range(len(predicate)):
            prediction2id[predicate[i]] = i
            id2predicate[i] = predicate[i]
    num_p = len(predicate)
    config.prediction2id = prediction2id
    config.id2predicate = id2predicate
    config.num_p = num_p


def load_data(path):
    text_spos = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        data = json.load(f)
        for item in data:
            text = item['text']
            spo_list = item['spo_list']
            text_spos.append({
                'text': text,
                'spo_list': spo_list
            })
    return text_spos


def loss_fn(pred, target):
    loss_fct = nn.BCELoss(reduction='none')
    return loss_fct(pred, target)


def train(train_data_loader, model4s, model4po, optimizer):
    for epoch in range(config.EPOCH):
        begin_time = time.time()
        model4s.train()
        model4po.train()
        train_loss = 0.
        for bi, batch in enumerate(train_data_loader):
            if bi >= len(train_data_loader) // config.batch_size:
                break

            """
            一系列指标：
                batch_token_ids: [1, 256] 
                    input id 输入字符编码
                batch_mask_ids: [1, 256]
                    mask id 每个字符是否参与transformer 是否参与计算
                batch_segment_ids: [1, 256]
                    segment：段
                    指定输入中每个字符分别是第几句话（段）
                batch_subject_ids: [1, 2]
                    subject: 主体
                    一个主体的起始和结束位置，一个主体一个主体的训练，不是所有主体一起训练
                    以主体为单位去训练
                batch_subject_labels: [1, 256, 2]
                    subject: 主体
                    主体标签，每个字符是主体的起始和结束位置标签
                batch_object_labels: [1, 256, 23, 2]
                    object: 客体
                    客体标签，每个字符是否与已确定的主体有关系，如果有关系确定是什么关系，
                    并且确定客体的起始和终止位置标签
            """
            batch_token_ids, batch_mask_ids, batch_segment_ids, batch_subject_labels, batch_subject_ids, batch_object_labels = batch
            batch_token_ids = torch.tensor(batch_token_ids, dtype=torch.long)
            batch_mask_ids = torch.tensor(batch_mask_ids, dtype=torch.long)
            batch_segment_ids = torch.tensor(batch_segment_ids, dtype=torch.long)
            batch_subject_labels = torch.tensor(batch_subject_labels, dtype=torch.float)
            batch_object_labels = torch.tensor(batch_object_labels, dtype=torch.float).view(config.batch_size,
                                                                                            config.max_seq_len,
                                                                                            config.num_p * 2)
            batch_subject_ids = torch.tensor(batch_subject_ids, dtype=torch.int)

            batch_subject_labels_pred, hidden_states = model4s(batch_token_ids, batch_mask_ids, batch_segment_ids)
            loss4s = loss_fn(batch_subject_labels_pred, batch_subject_labels.to(torch.float32))
            loss4s = torch.mean(loss4s, dim=2, keepdim=False) * batch_mask_ids
            loss4s = torch.sum(loss4s)
            loss4s = loss4s / torch.sum(batch_mask_ids)

            batch_object_labels_pred = model4po(hidden_states, batch_subject_ids, batch_mask_ids)
            loss4po = loss_fn(batch_object_labels_pred, batch_object_labels.to(torch.float32))
            loss4po = torch.mean(loss4po, dim=2, keepdim=False) * batch_mask_ids
            loss4po = torch.sum(loss4po)
            loss4po = loss4po / torch.sum(batch_mask_ids)

            loss = loss4s + loss4po
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item())
            print('batch:', bi, 'loss:', float(loss.item()))

        print('final train_loss:', train_loss / len(train_data_loader) * config.batch_size, 'cost time:',
              time.time() - begin_time)

    del train_data_loader
    gc.collect();

    return {
        "model4s_state_dict": model4s.state_dict(),
        "model4po_state_dict": model4po.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
    }


def extract_spoes(text, model4s, model4po):
    """
    return: a list of many tuple of (s, p, o)
    """
    # 处理text
    with torch.no_grad():
        tokenizer = config.tokenizer
        max_seq_len = config.max_seq_len
        token_ids = torch.tensor(
            tokenizer.encode(text, max_length=max_seq_len, pad_to_max_length=True, add_special_tokens=True)).view(1, -1)
        if len(text) > max_seq_len - 2:
            text = text[:max_seq_len - 2]
        mask_ids = torch.tensor([1] * (len(text) + 2) + [0] * (max_seq_len - len(text) - 2)).view(1, -1)
        segment_ids = torch.tensor([0] * max_seq_len).view(1, -1)
        subject_labels_pred, hidden_states = model4s(token_ids, mask_ids, segment_ids)
        subject_labels_pred = subject_labels_pred.cpu()
        subject_labels_pred[0, len(text) + 2:, :] = 0
        start = np.where(subject_labels_pred[0, :, 0] > 0.4)[0]
        end = np.where(subject_labels_pred[0, :, 1] > 0.4)[0]

        subjects = []
        for i in start:
            j = end[end >= i]
            if len(j) > 0:
                j = j[0]
                subjects.append((i, j))

        if len(subjects) == 0:
            return []
        subject_ids = torch.tensor(subjects).view(1, -1)

        spoes = []
        for s in subjects:
            object_labels_pred = model4po(hidden_states, subject_ids, mask_ids)
            object_labels_pred = object_labels_pred.view((1, max_seq_len, config.num_p, 2)).cpu()
            object_labels_pred[0, len(text) + 2:, :, :] = 0
            start = np.where(object_labels_pred[0, :, :, 0] > 0.4)
            end = np.where(object_labels_pred[0, :, :, 1] > 0.4)

            for _start, predicate1 in zip(*start):
                for _end, predicate2 in zip(*end):
                    if _start <= _end and predicate1 == predicate2:
                        spoes.append((s, predicate1, (_start, _end)))
                        break

    id_str = ['[CLS]']
    i = 1
    index = 0
    while i < token_ids.shape[1]:
        if token_ids[0][i] == 102:
            break

        word = tokenizer.decode(token_ids[0, i:i + 1])
        word = re.sub('#+', '', word)
        if word != '[UNK]':
            id_str.append(word)
            index += len(word)
            i += 1
        else:
            j = i + 1
            while j < token_ids.shape[1]:
                if token_ids[0][j] == 102:
                    break
                word_j = tokenizer.decode(token_ids[0, j:j + 1])
                if word_j != '[UNK]':
                    break
                j += 1
            if token_ids[0][j] == 102 or j == token_ids.shape[1]:
                while i < j - 1:
                    id_str.append('')
                    i += 1
                id_str.append(text[index:])
                i += 1
                break
            else:
                index_end = text[index:].find(word_j)
                word = text[index:index + index_end]
                id_str.append(word)
                index += index_end
                i += 1
    res = []
    for s, p, o in spoes:
        s_start = s[0]
        s_end = s[1]
        sub = ''.join(id_str[s_start:s_end + 1])
        o_start = o[0]
        o_end = o[1]
        obj = ''.join(id_str[o_start:o_end + 1])
        res.append((sub, config.id2predicate[p], obj))

    return res


class SPO(tuple):
    def __init__(self, spo):
        self.spox = (
            tuple(config.tokenizer.tokenize(spo[0])),
            spo[1],
            tuple(config.tokenizer.tokenize(spo[2])),
        )

    def __hash__(self):
        return self.spox.__hash__()

    def __eq__(self, spo):
        return self.spox == spo.spox


def evaluate(data, is_print, model4s, model4po):
    X, Y, Z = 1e-10, 1e-10, 1e-10
    for d in data:
        R = set([SPO(spo) for spo in extract_spoes(d['text'], model4s, model4po)])  # 模型提取出的三元组数目
        T = set([SPO(spo) for spo in d['spo_list']])  # 正确的三元组数目
        if is_print:
            print('text:', d['text'])
            print('R:', R)
            print('T:', T)
        X += len(R & T)  # 模型提取出的三元组数目中正确的个数
        Y += len(R)  # 模型提取出的三元组个数
        Z += len(T)  # 正确的三元组总数
    f1, precision, recall = 2 * X / (Y + Z), X / Y, X / Z

    return f1, precision, recall


def run_train():
    load_schema(config.PATH_SCHEMA)  # 加载23种关系
    train_path = config.PATH_TRAIN
    all_data = load_data(train_path)  # 加载训练数据，spo序列
    random.shuffle(all_data)

    # 8:2划分训练集、验证集
    idx = int(len(all_data) * 0.8)
    train_data = all_data[:idx]
    valid_data = all_data[idx:]

    # train
    train_data_loader = IterableDataset(train_data, True)
    num_train_data = len(train_data)
    checkpoint = torch.load(config.PATH_MODEL)

    """
    model for 主体：预测主体位置
    model for 关系 & 客体：预测客体位置和主客体关系
    
    流程：
        先通过 model4s 找到主体（比如百日咳），然后通过 model4po 找到客体和关系（咳嗽、症状）
        
    问题：
        想想为什么分成两个模型？不能放在一个模型中都预测了吗？
    """
    model4s = Model4s()
    model4s.load_state_dict(checkpoint['model4s_state_dict'])
    # model4s.cuda()

    model4po = Model4po()
    model4po.load_state_dict(checkpoint['model4po_state_dict'])
    # model4po.cuda()

    param_optimizer = list(model4s.named_parameters()) + list(model4po.named_parameters())
    no_decay = ['bias', 'LayerNorm.bias', 'LayerNorm.weight']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)], 'weight_decay': 0.01},
        {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
    ]

    lr = config.learning_rate
    optimizer = AdamW(optimizer_grouped_parameters, lr=lr)
    optimizer.load_state_dict(checkpoint['optimizer_state_dict'])

    checkpoint = train(train_data_loader, model4s, model4po, optimizer)

    del train_data
    gc.collect()
    # save
    model_path = config.PATH_SAVE
    torch.save(checkpoint, model_path)
    print('saved!')

    # valid
    model4s.eval()
    model4po.eval()
    f1, precision, recall = evaluate(valid_data, True, model4s, model4po)
    print('f1: %.5f, precision: %.5f, recall: %.5f' % (f1, precision, recall))


def load_model():
    load_schema(config.PATH_SCHEMA)
    checkpoint = torch.load(config.PATH_MODEL, map_location='cpu')

    model4s = Model4s()
    model4s.load_state_dict(checkpoint['model4s_state_dict'])
    # model4s.cuda()

    model4po = Model4po()
    model4po.load_state_dict(checkpoint['model4po_state_dict'])
    # model4po.cuda()

    return model4s, model4po


def get_triples(content, model4s, model4po):
    if len(content) == 0:
        return []
    text_list = content.split('。')[:-1]
    res = []
    for text in text_list:
        if len(text) > 128:
            text = text[:128]
        triples = extract_spoes(text, model4s, model4po)
        res.append({
            'text': text,
            'triples': triples
        })
    return res

if __name__ == "__main__":

    with open(config.PATH_TRAIN, 'r', encoding="utf-8", errors='replace') as f:
        data = json.load(f)

        f1=open("train.json","w")

        json.dump(data,f1,ensure_ascii=False,indent=True)
        print("finish")

    # load_schema(config.PATH_SCHEMA)
    # model4s, model4po = load_model()
    #
    # text = "据报道称，新冠肺炎患者经常会发热、咳嗽，少部分患者会胸闷、=乏力，其病因包括: 1.自身免疫系统缺陷\n2.人传人。"
    #
    # res = get_triples(text, model4s, model4po)

    # print(res)

