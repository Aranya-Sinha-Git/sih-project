import argparse,json,pandas as pd,joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support,confusion_matrix,roc_auc_score,average_precision_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--out',default='models/sif_tfidf.joblib');a=p.parse_args();d=pd.read_csv(a.csv).dropna(subset=['narrative','sif_potential']);d=d[d.sif_potential.isin([0,1])]
xtr,xte,ytr,yte=train_test_split(d.narrative,d.sif_potential,test_size=.2,random_state=26165,stratify=d.sif_potential);m=Pipeline([('tfidf',TfidfVectorizer(ngram_range=(1,2),min_df=2)),('clf',LogisticRegression(max_iter=1000,class_weight='balanced'))]).fit(xtr,ytr);y=m.predict(xte);q=m.predict_proba(xte)[:,1];pre,rec,f1,_=precision_recall_fscore_support(yte,y,average='binary',zero_division=0);z={'precision':pre,'recall':rec,'f1':f1,'false_negative_rate':float(((yte==1)&(y==0)).sum()/max(1,(yte==1).sum())),'confusion_matrix':confusion_matrix(yte,y).tolist(),'roc_auc':roc_auc_score(yte,q)if yte.nunique()==2 else None,'pr_auc':average_precision_score(yte,q)if yte.nunique()==2 else None};joblib.dump(m,a.out);print(json.dumps(z,indent=2))
