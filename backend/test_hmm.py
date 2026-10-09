
from algorithms.hmm import RateHMM

hmm = RateHMM()

print("Testing HMM predictions...\n")

for load in [0, 1, 2, 3, 4, 4, 3, 1, 0]:
    result = hmm.predict(load)
    print(f"Input LoadRank: {load} -> Prediction: {result}")

print("\nHMM test completed!")
