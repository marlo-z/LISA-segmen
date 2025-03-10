import torch
import torch.nn as nn
from transformers import CLIPImageProcessor, CLIPVisionConfig, CLIPVisionModel

# This is a custom class
# CLIPVisionModel, CLIPImageProcessor is embedded within this class
class CLIPVisionTower(nn.Module):
    def __init__(self, vision_tower, args, delay_load=False):
        super().__init__()

        self.is_loaded = False

        self.vision_tower_name = vision_tower
        self.select_layer = args.mm_vision_select_layer
        self.select_feature = getattr(args, "mm_vision_select_feature", "patch")

        if not delay_load:
            self.load_model()
        else:
            self.cfg_only = CLIPVisionConfig.from_pretrained(self.vision_tower_name)

    def load_model(self):
        self.image_processor = CLIPImageProcessor.from_pretrained(
            self.vision_tower_name
        )
        self.vision_tower = CLIPVisionModel.from_pretrained(
            self.vision_tower_name, low_cpu_mem_usage=True
        )
        self.vision_tower.requires_grad_(False)
        self.is_loaded = True

    def feature_select(self, image_forward_outs):
        # self.select_layer = -2
        # self.select_feature = "patch"

        image_features = image_forward_outs.hidden_states[self.select_layer]        # Question: why select 2nd to last layer?
        if self.select_feature == "patch":
            image_features = image_features[:, 1:]  # excludes cls token in front
        elif self.select_feature == "cls_patch":
            image_features = image_features         # includes cls token in front
        else:
            raise ValueError(f"Unexpected select feature: {self.select_feature}")
        return image_features

    @torch.no_grad()
    def forward(self, images, pool_features=False):
        if type(images) is list:
            image_features = []
            for image in images:
                image_forward_out = self.vision_tower(
                    image.to(device=self.device, dtype=self.dtype).unsqueeze(0),
                    output_hidden_states=True,
                )
                image_feature = self.feature_select(image_forward_out).to(image.dtype)
                image_features.append(image_feature)
        else:
            image_forward_outs = self.vision_tower(
                images.to(device=self.device, dtype=self.dtype),
                output_hidden_states=True,
            )
            # image_forward_outs: return type BaseModelOuputWithPooling

            # used when encoding cropped boxes --> only return 1 token per box
            if pool_features:
                image_features = image_forward_outs.pooler_output     
                # cls embed (last layer hiddent state[0], first token) --> apply linear + tanh activation
                # see: https://huggingface.co/docs/transformers/model_doc/clip#transformers.CLIPVisionModel
            else:
                image_features = self.feature_select(image_forward_outs).to(images.dtype)

        torch.cuda.empty_cache()
        return image_features

    @property
    def dummy_feature(self):
        return torch.zeros(1, self.hidden_size, device=self.device, dtype=self.dtype)

    @property
    def dtype(self):
        return self.vision_tower.dtype

    @property
    def device(self):
        return self.vision_tower.device

    @property
    def config(self):
        if self.is_loaded:
            return self.vision_tower.config
        else:
            return self.cfg_only

    @property
    def hidden_size(self):
        return self.config.hidden_size

    @property
    def num_patches(self):
        return (self.config.image_size // self.config.patch_size) ** 2
