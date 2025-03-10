from abc import ABCMeta

import torch
from diffusers.models.attention_processor import AttnProcessor, XFormersAttnProcessor, AttnProcessor2_0
from diffusers.utils import is_xformers_available
from torch import Tensor

from modules.model.WuerstchenModel import WuerstchenModel
from modules.modelSetup.BaseModelSetup import BaseModelSetup
from modules.modelSetup.mixin.ModelSetupDebugMixin import ModelSetupDebugMixin
from modules.modelSetup.mixin.ModelSetupDiffusionLossMixin import ModelSetupDiffusionLossMixin
from modules.modelSetup.mixin.ModelSetupDiffusionNoiseMixin import ModelSetupDiffusionNoiseMixin
from modules.modelSetup.stableDiffusion.checkpointing_util import enable_checkpointing_for_clip_encoder_layers
from modules.util.TrainProgress import TrainProgress
from modules.util.args.TrainArgs import TrainArgs
from modules.util.dtype_util import create_autocast_context
from modules.util.enum.AttentionMechanism import AttentionMechanism
from modules.util.enum.TrainingMethod import TrainingMethod


class BaseWuerstchenSetup(
    BaseModelSetup,
    ModelSetupDiffusionLossMixin,
    ModelSetupDebugMixin,
    ModelSetupDiffusionNoiseMixin,
    metaclass=ABCMeta,
):

    def setup_optimizations(
            self,
            model: WuerstchenModel,
            args: TrainArgs,
    ):
        if args.attention_mechanism == AttentionMechanism.DEFAULT:
            model.prior_prior.set_attn_processor(AttnProcessor())
        elif args.attention_mechanism == AttentionMechanism.XFORMERS and is_xformers_available():
            try:
                model.prior_prior.set_attn_processor(XFormersAttnProcessor())
            except Exception as e:
                print(
                    "Could not enable memory efficient attention. Make sure xformers is installed"
                    f" correctly and a GPU is available: {e}"
                )
        elif args.attention_mechanism == AttentionMechanism.SDP:
            model.prior_prior.set_attn_processor(AttnProcessor2_0())

        if args.gradient_checkpointing:
            model.prior_prior.enable_gradient_checkpointing()
            enable_checkpointing_for_clip_encoder_layers(model.prior_text_encoder)

        model.autocast_context, model.train_dtype = create_autocast_context(self.train_device, args.train_dtype, [
            args.weight_dtype,
            args.decoder_text_encoder_weight_dtype,
            args.decoder_weight_dtype,
            args.decoder_vqgan_weight_dtype,
            args.effnet_encoder_weight_dtype,
            args.text_encoder_weight_dtype,
            args.prior_weight_dtype,
            args.lora_weight_dtype if args.training_method == TrainingMethod.LORA else None,
            args.embedding_weight_dtype if args.training_method == TrainingMethod.EMBEDDING else None,
        ])

    def __alpha_cumprod(
            self,
            timesteps: Tensor,
            dim: int,
    ):
        # copied and modified from https://github.com/dome272/wuerstchen
        s = torch.tensor([0.008], device=timesteps.device, dtype=torch.float32)
        init_alpha_cumprod = torch.cos(s / (1 + s) * torch.pi * 0.5) ** 2
        alpha_cumprod = torch.cos((timesteps + s) / (1 + s) * torch.pi * 0.5) ** 2 / init_alpha_cumprod
        alpha_cumprod = alpha_cumprod.clamp(0.0001, 0.9999)
        alpha_cumprod = alpha_cumprod.view(timesteps.shape[0])
        while alpha_cumprod.dim() < dim:
            alpha_cumprod = alpha_cumprod.unsqueeze(-1)
        return alpha_cumprod

    def predict(
            self,
            model: WuerstchenModel,
            batch: dict,
            args: TrainArgs,
            train_progress: TrainProgress,
            *,
            deterministic: bool = False,
    ) -> dict:
        with model.autocast_context:
            latent_mean = 42.0
            latent_std = 1.0

            latent_image = batch['latent_image']
            scaled_latent_image = latent_image.add(latent_std).div(latent_mean)

            generator = torch.Generator(device=args.train_device)
            generator.manual_seed(train_progress.global_step)

            latent_noise = self._create_noise(scaled_latent_image, args, generator)

            timestep = self._get_timestep_continuous(
                deterministic,
                generator,
                scaled_latent_image.shape[0],
                args,
                train_progress.global_step,
            ).mul(1.08).add(0.001).clamp(0.001, 1.0)

            scaled_noisy_latent_image = self._add_noise_continuous(
                scaled_latent_image,
                latent_noise,
                timestep,
                self.__alpha_cumprod,
            )

            if args.train_text_encoder or args.training_method == TrainingMethod.EMBEDDING:
                text_encoder_output = model.prior_text_encoder(
                    batch['tokens'], output_hidden_states=True, return_dict=True
                )
                final_layer_norm = model.prior_text_encoder.text_model.final_layer_norm
                text_encoder_output = final_layer_norm(
                    text_encoder_output.hidden_states[-(1 + args.text_encoder_layer_skip)]
                )
            else:
                text_encoder_output = batch['text_encoder_hidden_state']

            latent_input = scaled_noisy_latent_image

            predicted_latent_noise = model.prior_prior(latent_input, timestep, text_encoder_output)

            model_output_data = {
                'loss_type': 'target',
                'predicted': predicted_latent_noise,
                'target': latent_noise,
                'timestep': timestep,
            }

            if args.debug_mode:
                with torch.no_grad():
                    self._save_text(
                        self._decode_tokens(batch['tokens'], model.prior_tokenizer),
                        args.debug_dir + "/training_batches",
                        "7-prompt",
                        train_progress.global_step,
                    )

                    # noise
                    self._save_image(
                        self._project_latent_to_image(latent_noise).clamp(-1, 1),
                        args.debug_dir + "/training_batches",
                        "1-noise",
                        train_progress.global_step
                    )

                    # predicted noise
                    self._save_image(
                        self._project_latent_to_image(predicted_latent_noise).clamp(-1, 1),
                        args.debug_dir + "/training_batches",
                        "2-predicted_noise",
                        train_progress.global_step
                    )

                    # noisy image
                    self._save_image(
                        self._project_latent_to_image(scaled_noisy_latent_image).clamp(-1, 1),
                        args.debug_dir + "/training_batches",
                        "3-noisy_image",
                        train_progress.global_step
                    )

                    # predicted image
                    alpha_cumprod = self.__alpha_cumprod(timestep, latent_noise.dim())
                    sqrt_alpha_prod = alpha_cumprod ** 0.5
                    sqrt_alpha_prod = sqrt_alpha_prod.flatten().reshape(-1, 1, 1, 1)

                    sqrt_one_minus_alpha_prod = (1 - alpha_cumprod) ** 0.5
                    sqrt_one_minus_alpha_prod = sqrt_one_minus_alpha_prod.flatten().reshape(-1, 1, 1, 1)

                    scaled_predicted_latent_image = \
                        (scaled_noisy_latent_image - predicted_latent_noise * sqrt_one_minus_alpha_prod) \
                        / sqrt_alpha_prod
                    self._save_image(
                        self._project_latent_to_image(scaled_predicted_latent_image).clamp(-1, 1),
                        args.debug_dir + "/training_batches",
                        "4-predicted_image",
                        model.train_progress.global_step
                    )

                    # image
                    self._save_image(
                        self._project_latent_to_image(scaled_latent_image).clamp(-1, 1),
                        args.debug_dir + "/training_batches",
                        "5-image",
                        model.train_progress.global_step
                    )

        return model_output_data

    def calculate_loss(
            self,
            model: WuerstchenModel,
            batch: dict,
            data: dict,
            args: TrainArgs,
    ) -> Tensor:
        losses = self._diffusion_losses(
            batch=batch,
            data=data,
            args=args,
            train_device=self.train_device,
            betas=None,
        )

        k = 1.0
        gamma = 1.0
        alpha_cumprod = self.__alpha_cumprod(data['timestep'], losses.dim())
        p2_loss_weight = (k + alpha_cumprod / (1 - alpha_cumprod)) ** -gamma

        return (losses * p2_loss_weight).mean()
